"""
Supporting classes and functions for tasks

"""

import logging
import time
import csv
import re
from itertools import repeat
from collections import namedtuple
from lib.rest_api import Rest, RestAPIException
from lib.config_items import (DeviceTemplateValues, DeviceTemplateAttached, DeviceTemplateAttach, DeviceModeCli,
                              ActionStatus, PolicyVsmartStatus, PolicyVsmartStatusException, PolicyVsmartActivate,
                              PolicyVsmartIndex, PolicyVsmartDeactivate)


def regex_search(regex, *fields):
    """
    Execute regular expression search on provided fields. Match fields in the order provided, stop on first match.
    :param regex: Pattern to match
    :param fields: One or more strings to match
    :return: True if a match is found on any field, False otherwise.
    """
    for match_field in fields:
        if re.search(regex, match_field):
            return True
    return False


class Tally:
    def __init__(self, *names):
        self._tally = dict(zip(names, repeat(0)))

    def __getattr__(self, item):
        return self._tally[item]

    def incr(self, item):
        self._tally[item] += 1


class Task:
    # Configuration parameters for wait_actions
    ACTION_INTERVAL = 10
    ACTION_TIMEOUT = 600

    log_count = Tally('debug', 'info', 'warning', 'error', 'critical')

    @classmethod
    def log_debug(cls, *args):
        cls._log('debug', *args)

    @classmethod
    def log_info(cls, *args):
        cls._log('info', *args)

    @classmethod
    def log_warning(cls, *args):
        cls._log('warning', *args)

    @classmethod
    def log_error(cls, *args):
        cls._log('error', *args)

    @classmethod
    def log_critical(cls, *args):
        cls._log('critical', *args)

    @classmethod
    def _log(cls, level, *args):
        logger = logging.getLogger(cls.__name__)
        getattr(logger, level)(*args)
        cls.log_count.incr(level)

    @classmethod
    def outcome(cls, success_msg, failure_msg):
        msg_list = list()
        if cls.log_count.critical:
            msg_list.append('{log.critical} critical'.format(log=cls.log_count))
        if cls.log_count.error:
            msg_list.append('{log.error} errors'.format(log=cls.log_count))
        if cls.log_count.warning:
            msg_list.append('{log.warning} warnings'.format(log=cls.log_count))

        msg = failure_msg if len(msg_list) > 0 else success_msg
        return msg.format(tally=', '.join(msg_list))

    @staticmethod
    def parser(default_workdir, task_args):
        raise NotImplementedError()

    @classmethod
    def runner(cls, api, parsed_args):
        raise NotImplementedError()

    @classmethod
    def index_iter(cls, backend, catalog_entry_iter):
        """
        Return an iterator of indexes loaded from backend. If backend is a Rest API instance, indexes are loaded
        from remote vManage via API. Otherwise items are loaded from local backup under the backend directory.
        :param backend: Rest api instance or directory name
        :param catalog_entry_iter: An iterator of CatalogEntry
        :return: Iterator of (<tag>, <title>, <index>, <item_cls>)
        """
        is_api = isinstance(backend, Rest)

        def load_index(index_cls, title):
            index = index_cls.get(backend) if is_api else index_cls.load(backend)
            cls.log_debug('No %s %s index' if index is None else 'Loaded %s %s index',
                          'remote' if is_api else 'local', title)
            return index

        all_index_iter = (
            (tag, title, load_index(index_cls, title), item_cls)
            for tag, title, index_cls, item_cls in catalog_entry_iter
        )
        return ((tag, title, index, item_cls) for tag, title, index, item_cls in all_index_iter if index is not None)

    @classmethod
    def attach_template(cls, api, work_dir, templates_iter, target_uuid_set=None):
        """
        Attach templates considering local backup as the source of truth (i.e. where input values are)
        :param api: Instance of Rest API
        :param work_dir: Directory containing saved items
        :param templates_iter: Iterator of (<template_name>, <saved_template_id>, <target_template_id>)
        :param target_uuid_set: (optional) Set of existing device uuids on target node.
                                When provided, attach only devices that were previously attached (on saved) and are on
                                target node but are not yet attached.
                                When absent, re-attach all currently attached devices on target.
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        def load_template_input(template_name, saved_id, target_id):
            if target_id is None:
                cls.log_debug('Skip %s, saved template is not on target node', template_name)
                return None

            saved_values = DeviceTemplateValues.load(work_dir, item_name=template_name, item_id=saved_id)
            if saved_values is None:
                cls.log_error('DeviceTemplateValues file not found: %s, %s', template_name, saved_id)
                return None
            if saved_values.is_empty:
                cls.log_debug('Skip %s, saved template has no attachments', template_name)
                return None

            target_attached_uuid_set = {uuid for uuid, _ in DeviceTemplateAttached.get_raise(api, target_id)}
            if target_uuid_set is None:
                allowed_uuid_set = target_attached_uuid_set
            else:
                saved_attached = DeviceTemplateAttached.load(work_dir, item_name=template_name, item_id=saved_id)
                if saved_attached is None:
                    cls.log_error('DeviceTemplateAttached file not found: %s, %s', template_name, saved_id)
                    return None
                saved_attached_uuid_set = {uuid for uuid, _ in saved_attached}
                allowed_uuid_set = target_uuid_set & saved_attached_uuid_set - target_attached_uuid_set

            input_list = saved_values.input_list(allowed_uuid_set)
            if len(input_list) == 0:
                cls.log_debug('Skip %s, no devices to attach', template_name)
                return None

            return input_list

        template_input_iter = ((name, target_id, load_template_input(name, saved_id, target_id))
                               for name, saved_id, target_id in templates_iter)
        input_dict = {template_name: (target_id, input_list)
                      for template_name, target_id, input_list in template_input_iter if input_list is not None}

        action_list = []
        if len(input_dict) > 0:
            action_worker = DeviceTemplateAttach(
                api.post(DeviceTemplateAttach.api_params(input_dict.values(), is_edited=target_uuid_set is None),
                         DeviceTemplateAttach.api_path.post)
            )
            cls.log_debug('Template attach requested: %s', action_worker.uuid)
            action_list.append((action_worker, ','.join(input_dict)))

        return action_list

    @classmethod
    def reattach_template(cls, api, templates_iter):
        """
        Reattach templates considering vManage as the source of truth (i.e. where input values are)
        :param api: Instance of Rest API
        :param templates_iter: Iterator of (<template_name>, <target_template_id>)
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        def get_template_input(template_id):
            uuid_list = [uuid for uuid, _ in DeviceTemplateAttached.get_raise(api, template_id)]
            values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(template_id, uuid_list),
                                                   DeviceTemplateValues.api_path.post))
            return values.input_list()

        template_input_dict = {template_name: (template_id, get_template_input(template_id))
                               for template_name, template_id in templates_iter}

        action_worker = DeviceTemplateAttach(
            api.post(DeviceTemplateAttach.api_params(template_input_dict.values(), is_edited=True),
                     DeviceTemplateAttach.api_path.post)
        )
        cls.log_debug('Template reattach requested: %s', action_worker.uuid)

        return [(action_worker, ','.join(template_input_dict))]

    @classmethod
    def detach_template(cls, api, template_index, filter_fn):
        """
        :param api: Instance of Rest API
        :param template_index: Instance of DeviceTemplateIndex
        :param filter_fn: Function used to filter elements to be returned
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        action_list = []
        for item_id, item_name in template_index.filtered_iter(filter_fn):
            devices_attached = DeviceTemplateAttached.get(api, item_id)
            if devices_attached is None:
                cls.log_warning('Failed to retrieve %s attached devices from vManage', item_name)
                continue

            uuids, personalities = zip(*devices_attached)
            # Personalities for all devices attached to the same template are always the same
            action_worker = DeviceModeCli(
                api.post(DeviceModeCli.api_params(personalities[0], *uuids), DeviceModeCli.api_path.post)
            )
            cls.log_debug('Template detach requested: %s', action_worker.uuid)
            action_list.append((action_worker, item_name))

        return action_list

    @classmethod
    def activate_policy(cls, api, policy_iter, is_edited=False):
        """
        :param api: Instance of Rest API
        :param policy_iter: An iterator of (<policy-id>, <policy-name>) tuples. It should yield a single entry.
        :param is_edited: (optional) When true it indicates reactivation of an already active policy (e.x. due to
                                     in-place modifications)
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        action_list = []
        try:
            PolicyVsmartStatus.get_raise(api).raise_for_status()
        except (RestAPIException, PolicyVsmartStatusException):
            cls.log_debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
        else:
            for policy_id, policy_name in policy_iter:
                if policy_id is None:
                    cls.log_debug('Skip, vSmart policy is not on target node')
                    continue

                action_worker = PolicyVsmartActivate(
                    api.post(PolicyVsmartActivate.api_params(is_edited), PolicyVsmartActivate.api_path.post, policy_id)
                )
                cls.log_debug('Policy activate requested: %s', action_worker.uuid)
                action_list.append((action_worker, policy_name))

        return action_list

    @classmethod
    def deactivate_policy(cls, api):
        action_list = []
        for item_id, item_name in PolicyVsmartIndex.get_raise(api).active_policy_iter():
            action_worker = PolicyVsmartDeactivate(api.post({}, PolicyVsmartDeactivate.api_path.post, item_id))
            cls.log_debug('Policy deactivate requested: %s', action_worker.uuid)
            action_list.append((action_worker, item_name))

        return action_list

    @classmethod
    def wait_actions(cls, api, action_list, log_context, raise_on_failure=False):
        """
        Wait for actions in action_list to complete
        :param api: Instance of Rest API
        :param action_list: [(<action_worker>, <action_info>), ...]. Where <action_worker> is an instance of ApiItem and
                            <action_info> is a str with information about the action.
        :param log_context: String providing context to log messages
        :param raise_on_failure: If True, raise exception on action failures
        :return: True if all actions completed with success. False otherwise.
        """

        def upper_first(input_string):
            return input_string[0].upper() + input_string[1:] if len(input_string) > 0 else ''

        cls.log_info(upper_first(log_context))
        result_list = []
        time_budget = cls.ACTION_TIMEOUT
        for action_worker, action_info in action_list:
            while True:
                action = ActionStatus.get(api, action_worker.uuid)
                if action is None:
                    cls.log_warning('Failed to retrieve action status from vManage')
                    result_list.append(False)
                    break

                if action.is_completed:
                    if action.is_successful:
                        cls.log_info('Completed %s', action_info)
                        result_list.append(True)
                    else:
                        cls.log_warning('Failed %s: %s', action_info, action.activity_details)
                        result_list.append(False)
                    break

                time_budget -= cls.ACTION_INTERVAL
                if time_budget > 0:
                    cls.log_info('Waiting...')
                    time.sleep(cls.ACTION_INTERVAL)
                else:
                    cls.log_warning('Wait time limit expired')
                    result_list.append(False)
                    break

        result = all(result_list)
        if result:
            cls.log_info('Completed %s', log_context)
        elif raise_on_failure:
            raise WaitActionsException('Failed {context}'.format(context=log_context))
        else:
            cls.log_warning('Failed %s', log_context)

        return result


class WaitActionsException(Exception):
    """ Exception indicating failure in one or more actions being monitored """
    pass


class Table:
    def __init__(self, *columns):
        self.header = tuple(columns)
        self._row_class = namedtuple('Row', columns)
        self._rows = list()

    def add(self, *row_values):
        self._rows.append(self._row_class(*row_values))

    def extend(self, row_values_iter):
        self._rows.extend(self._row_class(*row_values) for row_values in row_values_iter)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def _column_max_width(self, index):
        return max(
            len(self.header[index]),
            max((len(row[index]) for row in self._rows)) if len(self._rows) > 0 else 0
        )

    def pretty_iter(self):
        def cell_format(width, value):
            return ' {value:{width}} '.format(value=value, width=width-2)

        col_width_list = [2+self._column_max_width(index) for index in range(len(self.header))]
        border_line = '+' + '+'.join(('-'*col_width for col_width in col_width_list)) + '+'

        yield border_line
        yield '|' + '|'.join(cell_format(width, value) for width, value in zip(col_width_list, self.header)) + '|'
        yield border_line
        for row in self._rows:
            yield '|' + '|'.join(cell_format(width, value) for width, value in zip(col_width_list, row)) + '|'
        yield border_line

    def save(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(self.header)
            writer.writerows(self._rows)
