"""
Supporting classes and functions for tasks

"""

import logging
import time
import csv
import requests.exceptions
import re
from itertools import repeat, starmap
from collections import namedtuple
from lib.rest_api import Rest
from lib.config_items import (DeviceTemplateValues, DeviceTemplateAttached, DeviceTemplateAttach, DeviceModeCli,
                              ActionStatus)


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
    def attach_template(cls, api, saved_template_iter, work_dir, target_template_dict, target_uuid_set):
        """
        :param api: Instance of Rest API
        :param saved_template_iter: Iterator over saved templates to be inspected
        :param work_dir: Directory containing saved items
        :param target_template_dict: Templates on target node: {<template name>: <template id> ...}
        :param target_uuid_set: Set of existing device uuids on target node
        :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
        """
        action_list = []
        for saved_id, saved_name in saved_template_iter:
            cls.log_debug('Inspecting template %s', saved_name)
            saved_values = DeviceTemplateValues.load(work_dir, item_name=saved_name, item_id=saved_id)
            if saved_values is None:
                cls.log_error('Could not open %s backup file. ID: %s', saved_name, saved_id)
                continue
            if saved_values.is_empty:
                cls.log_debug('Skip, saved template has no attachments')
                continue

            target_id = target_template_dict.get(saved_name)
            if target_id is None:
                cls.log_debug('Skip, saved template is not on target node')
                continue

            try:
                target_attached_uuid_set = {uuid for uuid, _ in DeviceTemplateAttached.get_raise(api, target_id)}
            except requests.exceptions.HTTPError:
                cls.log_warning('Failed to retrieve %s attached devices from vManage', saved_name)
                continue

            # Limit input values to uuids on target vManage that are not yet attached
            input_values = saved_values.input_list(target_uuid_set - target_attached_uuid_set)
            if len(input_values) == 0:
                cls.log_debug('Skip, no further devices to attach')
                continue

            action_worker = DeviceTemplateAttach(
                api.post(DeviceTemplateAttach.api_params(target_id, input_values), DeviceTemplateAttach.api_path.post)
            )
            action_list.append((action_worker, saved_name))
            cls.log_debug('Template attach requested')

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
            action_list.append((action_worker, item_name))

        return action_list

    @classmethod
    def wait_actions(cls, api, action_list, log_context):
        """
        Wait for actions in action_list to complete
        :param api: Instance of Rest API
        :param action_list: [(<action_worker>, <action_info>), ...]. Where <action_worker> is an instance of ApiItem and
                            <action_info> is a str with information about the action.
        :param log_context: String providing context to log messages
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
                        cls.log_info('Done %s', action_info)
                        result_list.append(True)
                    else:
                        cls.log_warning('Failed %s', action_info)
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
            cls.log_info('Done %s', log_context)
        else:
            cls.log_warning('Failed %s', log_context)

        return result


class Table:
    def __init__(self, *columns):
        self.header = tuple(columns)
        self._row_class = namedtuple('Row', columns)
        self._rows = list()

    def add(self, *values):
        self._rows.append(self._row_class(*values))

    def extend(self, row_values_iter):
        self._rows.extend(starmap(self._row_class, row_values_iter))

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
        yield '|' + '|'.join(starmap(cell_format, zip(col_width_list, self.header))) + '|'
        yield border_line
        for row in self._rows:
            yield '|' + '|'.join(starmap(cell_format, zip(col_width_list, row))) + '|'
        yield border_line

    def save(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(self.header)
            writer.writerows(self._rows)
