"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.common
 This module implements supporting classes and functions for tasks
"""
import logging
import time
import csv
import re
from pathlib import Path
from shutil import rmtree
from collections import namedtuple
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_base import DATA_DIR
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
    def __init__(self, *counters):
        self._tally = {counter: 0 for counter in counters}

    def __getattr__(self, counter):
        return self._tally[counter]

    def incr(self, counter):
        self._tally[counter] += 1


class TaskArgs:
    def __init__(self, **kwargs):
        self.data = kwargs

    def __getattr__(self, field):
        if field not in self.data:
            raise AttributeError("'{cls_name}' object has no attribute '{attr}'".format(cls_name=type(self).__name__,
                                                                                        attr=field))
        return self.data[field]

    @classmethod
    def from_json(cls, json_obj, mapper=None):
        mapper_dict = mapper or {}
        kwargs = {arg_name: mapper_dict.get(arg_name, lambda x: x)(arg_value)
                  for arg_name, arg_value in json_obj.items()}
        return cls(**kwargs)


class Task:
    # Configuration parameters for wait_actions
    ACTION_INTERVAL = 10
    ACTION_TIMEOUT = 600

    SAVINGS_FACTOR = 1

    def __init__(self):
        self.log_count = Tally('debug', 'info', 'warning', 'error', 'critical')

    def log_debug(self, *args):
        self._log('debug', *args)

    def log_info(self, *args):
        self._log('info', *args)

    def log_warning(self, *args):
        self._log('warning', *args)

    def log_error(self, *args):
        self._log('error', *args)

    def log_critical(self, *args):
        self._log('critical', *args)

    def _log(self, level, *args):
        getattr(logging.getLogger(type(self).__name__), level)(*args)
        self.log_count.incr(level)

    def outcome(self, success_msg, failure_msg):
        msg_list = list()
        if self.log_count.critical:
            msg_list.append(f'{self.log_count.critical} critical')
        if self.log_count.error:
            msg_list.append(f'{self.log_count.error} errors')
        if self.log_count.warning:
            msg_list.append(f'{self.log_count.warning} warnings')

        msg = failure_msg if len(msg_list) > 0 else success_msg
        return msg.format(tally=', '.join(msg_list))

    @property
    def savings(self):
        """
        Estimate number of hours saved when running this task, when compared with performing the same steps manually.
        """
        return self.SAVINGS_FACTOR * self.log_count.info / 60

    @staticmethod
    def parser(task_args, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def is_api_required(parsed_args):
        return True

    def runner(self, parsed_args, api, task_output):
        raise NotImplementedError()

    def index_iter(self, backend, catalog_entry_iter):
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
            self.log_debug('%s %s %s index',
                           'No' if index is None else 'Loaded',
                           'remote' if is_api else 'local', info)
            return index

        all_index_iter = (
            (tag, info, load_index(index_cls, info), item_cls)
            for tag, info, index_cls, item_cls in catalog_entry_iter
        )
        return ((tag, info, index, item_cls) for tag, info, index, item_cls in all_index_iter if index is not None)

    @staticmethod
    def item_get(item_cls, backend, item_id, item_name, ext_name):
        if isinstance(backend, Rest):
            return item_cls.get(backend, item_id)
        else:
            return item_cls.load(backend, ext_name, item_name, item_id)

    @staticmethod
    def index_get(index_cls, backend):
        return index_cls.get(backend) if isinstance(backend, Rest) else index_cls.load(backend)

    def attach_template(self, api, workdir, ext_name, templates_iter, target_uuid_set=None):
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
                self.log_debug('Skip %s, saved template is not on target node', template_name)
                return None

            saved_values = DeviceTemplateValues.load(workdir, ext_name, template_name, saved_id)
            if saved_values is None:
                self.log_error('DeviceTemplateValues file not found: %s, %s', template_name, saved_id)
                return None
            if saved_values.is_empty:
                self.log_debug('Skip %s, saved template has no attachments', template_name)
                return None

            target_attached_uuid_set = {uuid for uuid, _ in DeviceTemplateAttached.get_raise(api, target_id)}
            if target_uuid_set is None:
                allowed_uuid_set = target_attached_uuid_set
            else:
                saved_attached = DeviceTemplateAttached.load(workdir, ext_name, template_name, saved_id)
                if saved_attached is None:
                    self.log_error('DeviceTemplateAttached file not found: %s, %s', template_name, saved_id)
                    return None
                saved_attached_uuid_set = {uuid for uuid, _ in saved_attached}
                allowed_uuid_set = target_uuid_set & saved_attached_uuid_set - target_attached_uuid_set

            input_list = saved_values.input_list(allowed_uuid_set)
            if len(input_list) == 0:
                self.log_debug('Skip %s, no devices to attach', template_name)
                return None

            return input_list

        def is_template_cli(template_name, saved_id):
            return DeviceTemplate.load(workdir, ext_name, template_name, saved_id, raise_not_found=True).is_type_cli

        template_input_list = [
            (name, target_id, load_template_input(name, saved_id, target_id), is_template_cli(name, saved_id))
            for name, saved_id, target_id in templates_iter
        ]
        return self._place_requests(api, template_input_list, is_edited=target_uuid_set is None)

    def reattach_template(self, api, templates_iter):
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
        return self._place_requests(api, template_input_list, is_edited=True)

    def _place_requests(self, api, template_input_list, is_edited):
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
            self.log_debug('Device template attach requested: %s', action_worker.uuid)
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
            self.log_debug('Device CLI template attach requested: %s', action_worker.uuid)
            action_list.append((action_worker, ','.join(cli_input_dict)))

        return action_list

    def detach_template(self, api, template_index, filter_fn):
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
                self.log_warning('Failed to retrieve %s attached devices from vManage', item_name)
                continue

            uuids, personalities = zip(*devices_attached)
            # Personalities for all devices attached to the same template are always the same
            action_worker = DeviceModeCli(
                api.post(DeviceModeCli.api_params(personalities[0], *uuids), DeviceModeCli.api_path.post)
            )
            self.log_debug('Template detach requested: %s', action_worker.uuid)
            action_list.append((action_worker, item_name))

        return action_list

    def activate_policy(self, api, policy_id, policy_name, is_edited=False):
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
            self.log_debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
        else:
            action_worker = PolicyVsmartActivate(
                api.post(PolicyVsmartActivate.api_params(is_edited), PolicyVsmartActivate.api_path.post, policy_id)
            )
            self.log_debug('Policy activate requested: %s', action_worker.uuid)
            action_list.append((action_worker, policy_name))

        return action_list

    def deactivate_policy(self, api):
        action_list = []
        item_id, item_name = PolicyVsmartIndex.get_raise(api).active_policy
        if item_id is not None and item_name is not None:
            action_worker = PolicyVsmartDeactivate(api.post({}, PolicyVsmartDeactivate.api_path.post, item_id))
            self.log_debug('Policy deactivate requested: %s', action_worker.uuid)
            action_list.append((action_worker, item_name))

        return action_list

    def wait_actions(self, api, action_list, log_context, raise_on_failure=False):
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

        self.log_info(upper_first(log_context))
        result_list = []
        time_budget = Task.ACTION_TIMEOUT
        for action_worker, action_info in action_list:
            while True:
                action = ActionStatus.get(api, action_worker.uuid)
                if action is None:
                    self.log_warning('Failed to retrieve action status from vManage')
                    result_list.append(False)
                    break

                if action.is_completed:
                    result_list.append(action.is_successful)
                    if action_info is not None:
                        if action.is_successful:
                            self.log_info('Completed %s', action_info)
                        else:
                            self.log_warning('Failed %s: %s', action_info, action.activity_details)

                    break

                time_budget -= Task.ACTION_INTERVAL
                if time_budget > 0:
                    self.log_info('Waiting...')
                    time.sleep(Task.ACTION_INTERVAL)
                else:
                    self.log_warning('Wait time limit expired')
                    result_list.append(False)
                    break

        result = all(result_list)
        if result:
            self.log_info('Completed %s', log_context)
        elif raise_on_failure:
            raise WaitActionsException('Failed {context}'.format(context=log_context))
        else:
            self.log_warning('Failed %s', log_context)

        return result


class TaskException(Exception):
    """ Exception for Task errors """
    pass


class WaitActionsException(TaskException):
    """ Exception indicating failure in one or more actions being monitored """
    pass


class Table:
    def __init__(self, *columns):
        self.header = tuple(columns)
        self._row_class = namedtuple('Row', (f'column_{i}' for i in range(len(columns))))
        self._rows = list()

    def add(self, *row_values):
        self._rows.append(self._row_class(*row_values))

    def add_marker(self):
        self._rows.append(None)

    def extend(self, row_values_iter):
        self._rows.extend(self._row_class(*row_values) for row_values in row_values_iter)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        total_len = len(self._rows) - self._rows.count(None)
        return total_len if total_len > 0 else 0

    def _column_max_width(self, index):
        def cell_length(cell_value):
            return len(str(cell_value))

        return max(
            cell_length(self.header[index]),
            max((cell_length(row[index]) for row in self._rows if row is not None)) if len(self) > 0 else 0
        )

    def pretty_iter(self):
        def cell_format(width, value):
            return ' {value:{width}} '.format(value=str(value), width=width-2)

        col_width_list = [2+self._column_max_width(index) for index in range(len(self.header))]
        border_line = '+' + '+'.join(('-'*col_width for col_width in col_width_list)) + '+'

        yield border_line
        yield '|' + '|'.join(cell_format(width, value) for width, value in zip(col_width_list, self.header)) + '|'
        yield border_line

        done_content_row = False
        for row in self._rows:
            if row is not None:
                done_content_row = True
                yield '|' + '|'.join(cell_format(width, value) for width, value in zip(col_width_list, row)) + '|'
            elif done_content_row:
                done_content_row = False
                yield border_line

        if done_content_row:
            yield border_line

    def save(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(self.header)
            writer.writerows(row for row in self._rows if row is not None)


def clean_dir(target_dir_name, max_saved=99):
    """
    Clean target_dir_name directory if it exists. If max_saved is non-zero and target_dir_name exists, move it to a new
    directory name in sequence.
    :param target_dir_name: str with the directory to be cleaned
    :param max_saved: int indicating the maximum instances to keep. If 0, target_dir_name is just deleted.
    """
    target_dir = Path(DATA_DIR, target_dir_name)
    if target_dir.exists():
        if max_saved > 0:
            save_seq = range(max_saved)
            for elem in save_seq:
                save_path = Path(DATA_DIR, '{workdir}_{count}'.format(workdir=target_dir_name, count=elem+1))
                if elem == save_seq[-1]:
                    rmtree(save_path, ignore_errors=True)
                if not save_path.exists():
                    target_dir.rename(save_path)
                    return save_path.name
        else:
            rmtree(target_dir, ignore_errors=True)

    return False
