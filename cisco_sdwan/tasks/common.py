"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.common
 This module implements supporting classes and functions for tasks
"""
import logging
import time
import csv
import re
from itertools import repeat
from collections import namedtuple
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_vmanage import (DeviceTemplate, DeviceTemplateValues, DeviceTemplateAttached,
                                             DeviceTemplateAttach, DeviceTemplateCLIAttach, DeviceModeCli,
                                             ActionStatus, PolicyVsmartStatus, PolicyVsmartStatusException,
                                             PolicyVsmartActivate, PolicyVsmartIndex, PolicyVsmartDeactivate)


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
        :return: Iterator of (<tag>, <info>, <index>, <item_cls>)
        """
        is_api = isinstance(backend, Rest)

        def load_index(index_cls, info):
            index = index_cls.get(backend) if is_api else index_cls.load(backend)
            cls.log_debug('%s %s %s index',
                          'No' if index is None else 'Loaded', 'remote' if is_api else 'local', info)
            return index

        all_index_iter = (
            (tag, info, load_index(index_cls, info), item_cls)
            for tag, info, index_cls, item_cls in catalog_entry_iter
        )
        return ((tag, info, index, item_cls) for tag, info, index, item_cls in all_index_iter if index is not None)

    @classmethod
    def attach_template(cls, api, workdir, ext_name, templates_iter, target_uuid_set=None):
        """
        Attach templates considering local backup as the source of truth (i.e. where input values are)
        :param api: Instance of Rest API
        :param workdir: Directory containing saved items
        :param ext_name: Boolean passed to .load methods indicating whether extended item names should be used.
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

            saved_values = DeviceTemplateValues.load(workdir, ext_name, template_name, saved_id)
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
                saved_attached = DeviceTemplateAttached.load(workdir, ext_name, template_name, saved_id)
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

        def is_template_cli(template_name, saved_id):
            return DeviceTemplate.load(workdir, ext_name, template_name, saved_id, raise_not_found=True).is_type_cli

        template_input_list = [
            (name, target_id, load_template_input(name, saved_id, target_id), is_template_cli(name, saved_id))
            for name, saved_id, target_id in templates_iter
        ]
        return cls._place_requests(api, template_input_list, is_edited=target_uuid_set is None)

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

        def is_template_cli(template_id):
            return DeviceTemplate.get_raise(api, template_id).is_type_cli

        template_input_list = [
            (template_name, template_id, get_template_input(template_id), is_template_cli(template_id))
            for template_name, template_id in templates_iter
        ]
        return cls._place_requests(api, template_input_list, is_edited=True)

    @classmethod
    def _place_requests(cls, api, template_input_list, is_edited):
        action_list = []
        # Attach requests for from-feature device templates
        feature_input_dict = {
            template_name: (template_id, input_list)
            for template_name, template_id, input_list, is_cli in template_input_list
            if input_list is not None and not is_cli
        }
        if len(feature_input_dict) > 0:
            action_worker = DeviceTemplateAttach(
                api.post(DeviceTemplateAttach.api_params(feature_input_dict.values(), is_edited),
                         DeviceTemplateAttach.api_path.post)
            )
            cls.log_debug('Device template attach requested: %s', action_worker.uuid)
            action_list.append((action_worker, ','.join(feature_input_dict)))

        # Attach Requests for cli device templates
        cli_input_dict = {
            template_name: (template_id, input_list)
            for template_name, template_id, input_list, is_cli in template_input_list
            if input_list is not None and is_cli
        }
        if len(cli_input_dict) > 0:
            action_worker = DeviceTemplateCLIAttach(
                api.post(DeviceTemplateCLIAttach.api_params(cli_input_dict.values(), is_edited),
                         DeviceTemplateCLIAttach.api_path.post)
            )
            cls.log_debug('Device CLI template attach requested: %s', action_worker.uuid)
            action_list.append((action_worker, ','.join(cli_input_dict)))

        return action_list

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
    def activate_policy(cls, api, policy_id, policy_name, is_edited=False):
        """
        :param api: Instance of Rest API
        :param policy_id: ID of policy to activate
        :param policy_name: Name of policy to activate
        :param is_edited: (optional) When true it indicates reactivation of an already active policy (e.x. due to
                                     in-place modifications)
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        action_list = []
        if policy_id is None or policy_name is None:
            # No policy is active or policy not on target vManage
            return action_list

        try:
            PolicyVsmartStatus.get_raise(api).raise_for_status()
        except (RestAPIException, PolicyVsmartStatusException):
            cls.log_debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
        else:
            action_worker = PolicyVsmartActivate(
                api.post(PolicyVsmartActivate.api_params(is_edited), PolicyVsmartActivate.api_path.post, policy_id)
            )
            cls.log_debug('Policy activate requested: %s', action_worker.uuid)
            action_list.append((action_worker, policy_name))

        return action_list

    @classmethod
    def deactivate_policy(cls, api):
        action_list = []
        item_id, item_name = PolicyVsmartIndex.get_raise(api).active_policy
        if item_id is not None and item_name is not None:
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
                            <action_info> is a str with information about the action. Action_info can be None, in which
                            case no messages are logged for individual actions.
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
                    result_list.append(action.is_successful)
                    if action_info is not None:
                        if action.is_successful:
                            cls.log_info('Completed %s', action_info)
                        else:
                            cls.log_warning('Failed %s: %s', action_info, action.activity_details)

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
