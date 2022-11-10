"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.tasks.common
 This module implements supporting classes and functions for tasks
"""
import logging
import time
import csv
import re
import json
from pathlib import Path
from shutil import rmtree
from collections import namedtuple
from typing import List, Tuple, Iterator, Union, Optional, Any, Iterable, Type, TypeVar, Sequence, Mapping
from zipfile import ZipFile, ZIP_DEFLATED
from pydantic import ValidationError
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_base import DATA_DIR
from cisco_sdwan.base.models_vmanage import (DeviceTemplate, DeviceTemplateValues, DeviceTemplateAttached,
                                             DeviceTemplateAttach, DeviceTemplateCLIAttach, DeviceModeCli,
                                             ActionStatus, PolicyVsmartStatus, PolicyVsmartStatusException,
                                             PolicyVsmartActivate, PolicyVsmartIndex, PolicyVsmartDeactivate,
                                             Device, ConfigGroupDeploy, ConfigGroupAssociated, ConfigGroupValues,
                                             ConfigGroupRules)

T = TypeVar('T')


def regex_search(regex: str, *fields: str, inverse: bool = False) -> bool:
    """
    Execute regular expression search on provided fields. Match fields in the order provided. Behavior is determined
    by the inverse field. With inverse False (default), returns True (i.e. match) if pattern matches any field. When
    inverse is True, returns True if pattern does not match all fields
    @param regex: Pattern to match
    @param fields: One or more strings to match
    @param inverse: False (default), or True to invert the match behavior.
    @return: True if a match is found on any field, False otherwise.
    """
    op_fn = all if inverse else any  # Logical AND across all fields, else logical OR
    return op_fn(inverse ^ bool(re.search(regex, match_field)) for match_field in fields)


class Tally:
    def __init__(self, *counters):
        self._tally = {counter: 0 for counter in counters}

    def __getattr__(self, counter):
        return self._tally[counter]

    def incr(self, counter):
        self._tally[counter] += 1


class TableFilter:
    def __init__(self, regex: str, column: Optional[int] = None, inverse: bool = False):
        """
        Table row filter used by 'Table.filtered'
        @param regex: Pattern to match
        @param column: Column that the filter should match. When None, filter matches if any column matches the pattern.
        @param inverse: If False (default) the filter returns True on matches. That is, a row that matches is allowed
                        by the filter. When True, this is inverted; row that does not match is allowed by the filter.
        """
        if column is not None and column < 0:
            raise ValueError('Column value, when provided, must be a positive integer')

        self.regex_pattern = re.compile(regex)
        self.column = column
        self.inverse = inverse

    def __call__(self, table_row: tuple) -> bool:
        """
        Callable used by 'Table.filtered' to evaluate whether a row should be allowed.
        @return: True if row is allowed by the filter. False otherwise.
        """
        def match_column(column_value) -> bool:
            if column_value is None:
                return True

            return self.regex_pattern.search(str(column_value)) is not None

        # Table row is None when that is a marker row
        if table_row is None:
            return True

        # When column is not provided, any column match is a row match
        if self.column is None:
            return self.inverse ^ any(match_column(cell_value) for cell_value in table_row)

        # With column provided, match on that particular column is a row match
        return self.inverse ^ match_column(table_row[self.column])


class Table:
    DECIMAL_DIGITS = 1  # Number of decimal digits for float values

    def __init__(self, *columns: str, name: Optional[str] = None, meta: Optional[str] = None) -> None:
        self.header = tuple(columns)
        self.name = name
        self.meta = meta
        self._row_class = namedtuple('Row', (f'column_{i}' for i in range(len(columns))))
        self._rows = list()

    def filtered(self, *filter_fns: TableFilter):
        """
        Returns a new Table instance constructed off this Table object, with its rows filtered by evaluation of
        one or more TableFilters. A row is included if it is allowed by all TableFilters.
        @param filter_fns: one or more TableFilter instances
        @return: New Table instance containing the filtered rows
        """
        new_table = Table(*self.header, name=self.name, meta=self.meta)
        new_table._rows = [row for row in self if all(filter_fn(row) for filter_fn in filter_fns)]

        return new_table

    @staticmethod
    def process_value(value):
        return round(value, Table.DECIMAL_DIGITS) if isinstance(value, float) else value

    def add(self, *row_values):
        self._rows.append(self._row_class(*map(self.process_value, row_values)))

    def add_marker(self):
        self._rows.append(None)

    def extend(self, row_values_iter):
        self._rows.extend(self._row_class(*map(self.process_value, row_values)) for row_values in row_values_iter)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        total_len = len(self._rows) - self._rows.count(None)
        return total_len if total_len > 0 else 0

    def __str__(self):
        return '\n'.join(self.pretty_iter())

    def _column_max_width(self, index):
        def cell_length(cell_value):
            return len(str(cell_value))

        return max(
            cell_length(self.header[index]),
            max((cell_length(row[index]) for row in self._rows if row is not None)) if len(self) > 0 else 0
        )

    def pretty_iter(self):
        def cell_format(width, value):
            return f' {str(value):{width - 2}} '

        def border(line_ch: str, int_edge_ch: str = '+', ext_edge_ch: str = '+') -> str:
            return ext_edge_ch + int_edge_ch.join((line_ch * col_width for col_width in col_width_list)) + ext_edge_ch

        col_width_list = [2 + self._column_max_width(index) for index in range(len(self.header))]
        border_line = border('-')
        header_border_line = border('=', '=')

        if self.name is not None:
            yield f"*** {self.name} ***"

        yield header_border_line
        yield '|' + '|'.join(cell_format(width, value) for width, value in zip(col_width_list, self.header)) + '|'
        yield header_border_line

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

    def dict(self) -> dict:
        table_dict = {
            "header": {
                "name": self.name or "",
                "title": {column_id: title for column_id, title in zip(self._row_class._fields, self.header)}
            },
            "data": [row._asdict() for row in self._rows if row is not None]
        }
        return table_dict

    def json(self, **dumps_kwargs: Any) -> str:
        return json.dumps(self.dict(), **dumps_kwargs)

    def save(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(self.header)
            writer.writerows(row for row in self._rows if row is not None)


def get_table_filters(exclude_regex: Optional[str], include_regex: Optional[str]) -> Sequence[TableFilter]:
    filters = []
    if exclude_regex is not None:
        filters.append(TableFilter(exclude_regex, inverse=True))
    if include_regex is not None:
        filters.append(TableFilter(include_regex))

    return filters


def filtered_tables(tables: Sequence[Table], *filter_fns: TableFilter) -> Sequence[Table]:
    if not filter_fns:
        return tables

    filtered_table_iter = (table.filtered(*filter_fns) for table in tables)

    return [filtered_table for filtered_table in filtered_table_iter if filtered_table]


class DryRunReport:
    def __init__(self):
        self._entries: List[str] = []

    def add(self, entry: str) -> None:
        self._entries.append(entry)

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def render(self) -> Iterator[str]:
        yield ""
        yield "### Dry-run actions preview ###"
        yield ""
        yield from (f"    {entry}" for entry in self)
        yield ""

    def __str__(self) -> str:
        return '\n'.join(self.render())


class Task:
    # Configuration parameters for wait_actions
    ACTION_INTERVAL = 10  # seconds
    ACTION_TIMEOUT = 1800  # 30 minutes

    SAVINGS_FACTOR = 1
    DRYRUN_LEVELS = {'info', 'warning', 'error', 'critical'}

    def __init__(self):
        self.log_count = Tally('debug', 'info', 'warning', 'error', 'critical')
        self.is_dryrun = False
        self.dryrun_report = DryRunReport()

    def log_debug(self, msg: str, *args, dryrun: bool = True) -> None:
        self._log('debug', msg, *args, dryrun=dryrun)

    def log_info(self, msg: str, *args, dryrun: bool = True) -> None:
        self._log('info', msg, *args, dryrun=dryrun)

    def log_warning(self, msg: str, *args, dryrun: bool = True) -> None:
        self._log('warning', msg, *args, dryrun=dryrun)

    def log_error(self, msg: str, *args, dryrun: bool = True) -> None:
        self._log('error', msg, *args, dryrun=dryrun)

    def log_critical(self, msg: str, *args, dryrun: bool = True) -> None:
        self._log('critical', msg, *args, dryrun=dryrun)

    def _log(self, level: str, msg: str, *args, dryrun: bool) -> None:
        """
        Logs a message
        @param level: Logging level
        @param msg: Log message
        @param args: Optional args to replace in msg via % operator
        @param dryrun: Whether to include this message to the dryrun report. Messages are added to the dryrun report if
                       this flag is True, the task is in dryrun mode and the level is in DRYRUN_LEVELS.
        """
        getattr(logging.getLogger(type(self).__name__), level)(f"DRY-RUN: {msg}" if self.is_dryrun else msg, *args)
        self.log_count.incr(level)

        if self.is_dryrun and dryrun and level in Task.DRYRUN_LEVELS:
            self.dryrun_report.add(msg % args if args else msg)

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
    def is_api_required(parsed_args) -> bool:
        return True

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        """
        Execute the task. If the task has some output to the user, that is returned via a list of objects. Objects in
        that list need to implement the __str__ method. If the task generates no output to the user None is returned.
        """
        raise NotImplementedError()

    def index_iter(self, backend, catalog_entry_iter):
        """
        Return an iterator of indexes loaded from backend. If backend is a Rest API instance, indexes are loaded
        from remote vManage via API. Otherwise, items are loaded from local backup under the backend directory.
        @param backend: Rest api instance or directory name
        @param catalog_entry_iter: An iterator of CatalogEntry
        @return: Iterator of (<tag>, <info>, <index>, <item_cls>)
        """
        is_api = isinstance(backend, Rest)

        def load_index(index_cls, info):
            index = index_cls.get(backend) if is_api else index_cls.load(backend)
            self.log_debug(f'{"No" if index is None else "Loaded"} {"remote" if is_api else "local"} {info} index')
            return index

        all_index_iter = (
            (tag, info, load_index(index_cls, info), item_cls)
            for tag, info, index_cls, item_cls in catalog_entry_iter
        )
        return ((tag, info, index, item_cls) for tag, info, index, item_cls in all_index_iter if index is not None)

    @staticmethod
    def item_get(item_cls: Type[T], backend: Union[Rest, str],
                 item_id: str, item_name: str, ext_name: bool) -> Union[T, None]:
        if isinstance(backend, Rest):
            return item_cls.get(backend, item_id)
        else:
            return item_cls.load(backend, ext_name, item_name, item_id)

    @staticmethod
    def index_get(index_cls: Type[T], backend: Union[Rest, str]) -> Union[T, None]:
        return index_cls.get(backend) if isinstance(backend, Rest) else index_cls.load(backend)

    def template_attach_data(self, api: Rest, workdir: str, ext_name: bool, templates_iter: Iterator[tuple],
                             target_uuid_set: Optional[set] = None) -> Tuple[list, bool]:
        """
        Prepare data for template attach considering local backup as the source of truth (i.e. where input values are)
        @param api: Instance of Rest API
        @param workdir: Directory containing saved items
        @param ext_name: Boolean passed to .load methods indicating whether extended item names should be used.
        @param templates_iter: Iterator of (<template_name>, <saved_template_id>, <target_template_id>)
        @param target_uuid_set: (optional) Set of existing device uuids on target node.
                                When provided, attach only devices that were previously attached (on saved) and are on
                                target node but are not yet attached.
                                When absent, re-attach all currently attached devices on target.
        @return: Tuple containing attach data (<template input list>, <isEdited>)
        """
        def load_template_input(template_name: str, saved_id: str, target_id: str) -> Union[list, None]:
            if target_id is None:
                self.log_debug(f'Skip {template_name}, saved template not on target node')
                return None

            saved_values = DeviceTemplateValues.load(workdir, ext_name, template_name, saved_id)
            if saved_values is None:
                self.log_error(f'DeviceTemplateValues file not found: {template_name}, {saved_id}')
                return None
            if saved_values.is_empty:
                self.log_debug(f'Skip {template_name}, saved template has no attachments')
                return None

            target_attached_uuid_set = {uuid for uuid, _ in DeviceTemplateAttached.get_raise(api, target_id)}
            if target_uuid_set is None:
                allowed_uuid_set = target_attached_uuid_set
            else:
                saved_attached = DeviceTemplateAttached.load(workdir, ext_name, template_name, saved_id)
                if saved_attached is None:
                    self.log_error(f'DeviceTemplateAttached file not found: {template_name}, {saved_id}')
                    return None
                saved_attached_uuid_set = {uuid for uuid, _ in saved_attached}
                allowed_uuid_set = target_uuid_set & saved_attached_uuid_set - target_attached_uuid_set

            input_list = saved_values.input_list(allowed_uuid_set)
            if len(input_list) == 0:
                self.log_debug(f'Skip template {template_name}, no devices to attach')
                return None

            return input_list

        def is_template_cli(template_name: str, saved_id: str) -> bool:
            return DeviceTemplate.load(workdir, ext_name, template_name, saved_id, raise_not_found=True).is_type_cli

        template_input_list = [
            (name, target_id, load_template_input(name, saved_id, target_id), is_template_cli(name, saved_id))
            for name, saved_id, target_id in templates_iter
        ]
        return template_input_list, target_uuid_set is None

    @staticmethod
    def template_reattach_data(api: Rest, templates_iter: Iterator[tuple]) -> Tuple[list, bool]:
        """
        Prepare data for template reattach considering vManage as the source of truth (i.e. where input values are)
        @param api: Instance of Rest API
        @param templates_iter: Iterator of (<template_name>, <target_template_id>)
        @return: Tuple containing attach data (<template input list>, <isEdited>)
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
        return template_input_list, True

    def template_attach(self, api: Rest, template_input_list: Sequence[tuple], is_edited: bool, *,
                        chunk_size: int = 200, log_context: str, raise_on_failure: bool = True) -> int:
        """
        Attach device templates to devices
        @param api: Instance of Rest API
        @param template_input_list: Sequence containing payload for template attachment
        @param is_edited: Boolean corresponding to the isEdited tag in the template attach payload
        @param chunk_size: Maximum number of device attachments per request
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @return: Number of attachment requests processed
        """
        def grouper(attach_cls, request_list):
            while True:
                section_dict = yield from chopper(chunk_size)
                if not section_dict:
                    continue

                request_list.append(...)
                attach_request_details = (
                    f"{template_name} ({', '.join(DeviceTemplateValues.input_list_devices(input_list))})"
                    for template_name, key_dict in section_dict.items() for input_list in key_dict.values()
                )
                self.log_info(f'Template attach: {", ".join(attach_request_details)}')

                if self.is_dryrun:
                    continue

                template_input_iter = (
                    (template_id, input_list)
                    for key_dict in section_dict.values() for template_id, input_list in key_dict.items()
                )
                action_worker = attach_cls(
                    api.post(attach_cls.api_params(template_input_iter, is_edited), attach_cls.api_path.post)
                )
                self.log_debug(f'Device template attach requested: {action_worker.uuid}')
                self.wait_actions(api, [(action_worker, ', '.join(section_dict))], log_context, raise_on_failure)

        def feeder(attach_cls, attach_data_iter):
            attach_reqs = []
            group = grouper(attach_cls, attach_reqs)
            next(group)
            for template_name, template_id, input_list in attach_data_iter:
                for input_entry in input_list:
                    group.send((template_name, template_id, input_entry))
            group.send(None)

            return attach_reqs

        # Attach requests for feature-based device templates
        feature_based_iter = ((template_name, template_id, input_list)
                              for template_name, template_id, input_list, is_cli in template_input_list
                              if input_list is not None and not is_cli)
        feature_based_reqs = feeder(DeviceTemplateAttach, feature_based_iter)

        # Attach Requests for cli device templates
        cli_based_iter = ((template_name, template_id, input_list)
                          for template_name, template_id, input_list, is_cli in template_input_list
                          if input_list is not None and is_cli)
        cli_based_reqs = feeder(DeviceTemplateCLIAttach, cli_based_iter)

        return len(feature_based_reqs + cli_based_reqs)

    def cfg_group_deploy_data(self, api: Rest, workdir: str, ext_name: bool,
                              cfg_group_iter: Iterator[Tuple[str, str, Union[str, None]]],
                              devices_map: Mapping[str, str]) -> Sequence[Tuple[str, str, Sequence]]:
        """
        Prepare data for config-group deploy assuming local backup as source of truth. Associate devices and
        pushing values as needed in preparation for the deployment.
        @param api: Instance of Rest API
        @param workdir: Directory containing saved items
        @param ext_name: Boolean passed to .load methods indicating whether extended item names should be used.
        @param cfg_group_iter: Iterator of (<config_group_name>, <saved_config_group_id>, <target_config_group_id>)
        @param devices_map: Mapping of {<uuid>: <name>, ...} with available devices on target node. Name may be None if
                            device has no hostname yet.
        @return: Sequence of (<config_group_id>, <config_group_name>, [<device uuid>, ...]) tuples
        """
        def associate_devices(config_grp_name: str, config_grp_saved_id: str, config_grp_target_id: str) -> bool:
            saved_associated = ConfigGroupAssociated.load(workdir, ext_name, config_grp_name, config_grp_saved_id)
            if saved_associated is None:
                self.log_debug(f"Skip config-group {config_grp_name} associate, no ConfigGroupAssociated file")
                return False

            # Associate devices in saved_associated that are available but not associated yet
            already_associated_uuids = set(
                ConfigGroupAssociated.get_raise(api, configGroupId=config_grp_target_id).uuids
            )
            diff_associated = saved_associated.filter(devices_map.keys() - already_associated_uuids, not_by_rule=True)
            if diff_associated.is_empty:
                self.log_debug(f"Skip config-group {config_grp_name} associate, no devices to associate")
                return False

            if not self.is_dryrun:
                diff_associated.put_raise(api, configGroupId=config_grp_target_id)

            self.log_info(f"Config-group {config_grp_name}, "
                          f"associate: {', '.join(devices_map.get(uuid) or uuid for uuid in diff_associated.uuids)}")
            return True

        def restore_rules(config_grp_name: str, config_grp_saved_id: str, config_grp_target_id: str) -> bool:
            saved_rules = ConfigGroupRules.load(workdir, ext_name, config_grp_name, config_grp_saved_id)
            if saved_rules is None:
                self.log_debug(f"Skip config-group {config_grp_name} restore rules, no ConfigGroupRules file")
                return False

            if self.is_dryrun:
                self.log_info(f"Config-group {config_grp_name}, associate (via automated rules): "
                              "device list is unknown during dry-run")
                return True

            matched_uuids = saved_rules.post_raise(api, config_grp_target_id)
            self.log_info(f"Config-group {config_grp_name}, associate (via automated rules): "
                          f"{', '.join(devices_map.get(uuid) or uuid for uuid in matched_uuids)}")

            return len(matched_uuids) > 0

        def restore_values(config_grp_name: str, config_grp_saved_id: str, config_grp_target_id: str):
            saved_values = ConfigGroupValues.load(workdir, ext_name, config_grp_name, config_grp_saved_id)
            if saved_values is None:
                self.log_debug(f"Skip config-group {config_grp_name} push values, no ConfigGroupValues file")
                return []

            # Restore values for devices in saved_values that are available
            diff_values = saved_values.filter(devices_map.keys())
            if diff_values.is_empty:
                self.log_debug(f"Skip config-group {config_grp_name} push values, no values to push")
                return []

            if not self.is_dryrun:
                try:
                    diff_uuids = diff_values.put_raise(api, configGroupId=config_grp_target_id)
                except (RestAPIException, ValidationError) as ex:
                    # Pydantic validation error raised when the saved values fail local model validation.
                    # RestAPIException when vManage validation fails.
                    self.log_error(f"Failed: Config-group {config_grp_name} push values: {ex}")
                    return []
            else:
                diff_uuids = list(diff_values.uuids)

            self.log_info(f"Config-group {config_grp_name}, "
                          f"push values: {', '.join(devices_map.get(uuid) or uuid for uuid in diff_uuids)}")

            return diff_uuids

        deploy_data = []
        for group_name, saved_id, target_id in cfg_group_iter:
            if target_id is None:
                self.log_debug(f'Skip {group_name}, saved config-group not on target node')
                continue

            rules_associates = restore_rules(group_name, saved_id, target_id)
            direct_associates = associate_devices(group_name, saved_id, target_id)

            if not direct_associates and not rules_associates:
                continue

            affected_uuids = restore_values(group_name, saved_id, target_id)
            if not affected_uuids:
                continue

            deploy_data.append((target_id, group_name, affected_uuids))

        return deploy_data

    def cfg_group_deploy(self, api: Rest, deploy_data: Sequence[Tuple[str, str, Sequence]],
                         devices_map: Mapping[str, str], *, chunk_size: int = 200, log_context: str,
                         raise_on_failure: bool = True) -> int:
        """
        Deploy config-groups to devices
        @param api: Instance of Rest API
        @param deploy_data: Sequence of (<config_group_id>, <config_group_name>, [<device uuid>, ...]) tuples
        @param devices_map: Mapping of {<uuid>: <name>, ...} with available devices on target node. Name may be None if
                            device has no hostname yet.
        @param chunk_size: Maximum number of device deployments per request
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @return: Number of deploy requests processed
        """
        def grouper(request_list):
            while True:
                section_dict = yield from chopper(chunk_size)
                if not section_dict:
                    continue

                wait_list = []
                for group_id, key_dict in section_dict.items():
                    request_list.append(...)
                    self.log_info(f'Config-group deploy: {request_details(key_dict, devices_map)}')

                    if self.is_dryrun:
                        continue

                    action_worker = ConfigGroupDeploy(
                        api.post(ConfigGroupDeploy.api_params(uuid for uuids in key_dict.values() for uuid in uuids),
                                 ConfigGroupDeploy.api_path.resolve(configGroupId=group_id).post)
                    )
                    wait_list.append((action_worker, ', '.join(key_dict)))
                    self.log_debug(f'Config-group deploy requested: {action_worker.uuid}')

                if wait_list:
                    self.wait_actions(api, wait_list, log_context, raise_on_failure)

        deploy_reqs = []
        group = grouper(deploy_reqs)
        next(group)

        for config_grp_id, config_grp_name, device_id_list in deploy_data:
            for device_id in device_id_list:
                group.send((config_grp_id, config_grp_name, device_id))
        group.send(None)

        return len(deploy_reqs)

    def template_detach(self, api: Rest, template_iter: Iterator[Tuple[str, str]],
                        devices_map: Optional[Mapping[str, str]] = None, *,
                        chunk_size: int = 200, log_context: str, raise_on_failure: bool = True) -> int:
        """
        Detach devices from device templates
        @param api: Instance of Rest API
        @param template_iter: Iterator of (<template id>, <template name>) tuples containing templates to detach
        @param devices_map: Mapping of {<uuid>: <name>, ...} containing allowed devices to detach. If None, all attached
                            devices are detached.
        @param chunk_size: Maximum number of devices per detachment request
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @return: Number of detach requests processed
        """
        def grouper(request_list):
            while True:
                section_dict = yield from chopper(chunk_size)
                if not section_dict:
                    continue

                wait_list = []
                for device_type, key_dict in section_dict.items():
                    request_list.append(...)
                    self.log_info(f'Template detach: {request_details(key_dict, devices_map)}')

                    if self.is_dryrun:
                        continue

                    uuid_iter = (uuid for device_id_list in key_dict.values() for uuid in device_id_list)
                    action_worker = DeviceModeCli(
                        api.post(DeviceModeCli.api_params(device_type, *uuid_iter), DeviceModeCli.api_path.post)
                    )
                    wait_list.append((action_worker, ', '.join(key_dict)))
                    self.log_debug(f'Device template attach requested: {action_worker.uuid}')

                if wait_list:
                    self.wait_actions(api, wait_list, log_context, raise_on_failure)

        detach_reqs = []
        group = grouper(detach_reqs)
        next(group)

        if devices_map is None:
            devices_map = dict(device_iter(api, default=None))

        for template_id, template_name in template_iter:
            devices_attached = DeviceTemplateAttached.get(api, template_id)
            if devices_attached is None:
                self.log_warning(f'Failed to retrieve {template_name} attached devices from vManage')
                continue
            for device_id, personality in devices_attached:
                if device_id in devices_map:
                    group.send((personality, template_name, device_id))
        group.send(None)

        return len(detach_reqs)

    def cfg_group_dissociate(self, api: Rest, cfg_group_iter: Iterator[Tuple[str, str]],
                             devices_map: Optional[Mapping[str, str]] = None, *,
                             chunk_size: int = 200, log_context: str, raise_on_failure: bool = True) -> int:
        """
        Dissociate devices from config-groups
        @param api: Instance of Rest API
        @param cfg_group_iter: Iterator of (<group id>, <group name>) tuples containing config-groups to dissociate
        @param devices_map: Mapping of {<uuid>: <name>, ...} containing allowed devices to dissociate. If None,
                            dissociate all associated devices.
        @param chunk_size: Maximum number of devices per association delete request
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @return: Number of associate delete requests processed
        """
        def grouper(request_list):
            while True:
                section_dict = yield from chopper(chunk_size)
                if not section_dict:
                    continue

                wait_list = []
                for group_id, key_dict in section_dict.items():
                    request_list.append(...)
                    self.log_info(f'Config-group dissociate: {request_details(key_dict, devices_map)}')

                    if self.is_dryrun:
                        continue

                    uuid_iter = (uuid for device_id_list in key_dict.values() for uuid in device_id_list)
                    action_worker = ConfigGroupAssociated.delete_raise(api, uuid_iter, configGroupId=group_id)
                    wait_list.append((action_worker, ', '.join(key_dict)))
                    self.log_debug(f'Config-group device dissociate requested: {action_worker.uuid}')

                if wait_list:
                    self.wait_actions(api, wait_list, log_context, raise_on_failure)

        dissociate_reqs = []
        group = grouper(dissociate_reqs)
        next(group)

        if devices_map is None:
            devices_map = dict(device_iter(api, default=None))

        for config_grp_id, config_grp_name in cfg_group_iter:
            devices_associated = ConfigGroupAssociated.get(api, configGroupId=config_grp_id)
            if devices_associated is None:
                self.log_warning(f'Failed to retrieve {config_grp_name} associated devices from vManage')
                continue
            for device_id in devices_associated.filter(not_by_rule=True).uuids:
                if device_id in devices_map:
                    group.send((config_grp_id, config_grp_name, device_id))
        group.send(None)

        return len(dissociate_reqs)

    def cfg_group_rules_delete(self, api: Rest, cfg_group_iter: Iterator[Tuple[str, str]]) -> int:
        """
        Delete config-group device association automated rules
        @param api: Instance of Rest API
        @param cfg_group_iter: Iterator of (<group id>, <group name>) tuples containing config-groups to inspect
        @return: Number of automated rules delete requests processed
        """
        delete_req_count = 0
        for config_grp_id, config_grp_name in cfg_group_iter:
            rules = ConfigGroupRules.get(api, configGroupId=config_grp_id)
            if rules is None:
                self.log_warning(f'Failed to retrieve {config_grp_name} automated rules from vManage')
                continue
            for rule_id in rules:
                delete_req_count += 1
                self.log_info(f'Config-group {config_grp_name} delete automated rule: {rule_id}')

                if self.is_dryrun:
                    continue

                try:
                    ConfigGroupRules.delete_raise(api, config_grp_id, rule_id)
                except RestAPIException as ex:
                    self.log_error(f'Failed to delete config-group {config_grp_name} automated rule {rule_id}: {ex}')

        return delete_req_count

    def policy_activate(self, api: Rest, policy_id: Optional[str], policy_name: Optional[str], *,
                        log_context: str, raise_on_failure: bool = True, is_edited: bool = False) -> int:
        """
        Activate a centralized policy
        @param api: Instance of Rest API
        @param policy_id: ID of policy to activate
        @param policy_name: Name of policy to activate
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @param is_edited: (optional) When true it indicates reactivation of an already active policy (e.x. due to
                                     in-place modifications)
        @return: Number of policy activate requests processed
        """
        activate_reqs = []
        try:
            if policy_id is None or policy_name is None:
                raise StopIteration()
            PolicyVsmartStatus.get_raise(api).raise_for_status()
        except (RestAPIException, PolicyVsmartStatusException):
            self.log_debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
        except StopIteration:
            self.log_debug('No policy is active or policy not on target vManage')
        else:
            activate_reqs.append(...)
            self.log_info(f'vSmart policy activate: {policy_name}')

            if not self.is_dryrun:
                action_worker = PolicyVsmartActivate(
                    api.post(PolicyVsmartActivate.api_params(is_edited), PolicyVsmartActivate.api_path.post, policy_id)
                )
                self.log_debug(f'Policy activate requested: {action_worker.uuid}')
                self.wait_actions(api, [(action_worker, policy_name)], log_context, raise_on_failure)

        return len(activate_reqs)

    def policy_deactivate(self, api: Rest, *, log_context: str, raise_on_failure: bool = True) -> int:
        """
        Deactivate the active centralized policy
        @param api: Instance of Rest API
        @param raise_on_failure: If True, raise exception on action failures
        @param log_context: Message to log during wait actions
        @return: Number of policy deactivate requests processed
        """
        deactivate_reqs = []
        policy_id, policy_name = PolicyVsmartIndex.get_raise(api).active_policy
        if policy_id is not None and policy_name is not None:
            deactivate_reqs.append(...)
            self.log_info(f'vSmart policy deactivate: {policy_name}')

            if not self.is_dryrun:
                action_worker = PolicyVsmartDeactivate(
                    api.post({}, PolicyVsmartDeactivate.api_path.post, policy_id)
                )
                self.log_debug(f'Policy deactivate requested: {action_worker.uuid}')
                self.wait_actions(api, [(action_worker, policy_name)], log_context, raise_on_failure)

        return len(deactivate_reqs)

    def wait_actions(self, api: Rest, action_list: List[tuple], log_context: str, raise_on_failure: bool) -> bool:
        """
        Wait for actions in action_list to complete
        @param api: Instance of Rest API
        @param action_list: [(<action_worker>, <action_info>), ...]. Where <action_worker> is an instance of ApiItem and
                            <action_info> is a str with information about the action. Action_info can be None, in which
                            case no messages are logged for individual actions.
        @param log_context: String providing context to log messages
        @param raise_on_failure: If True, raise exception on action failures
        @return: True if all actions completed with success. False otherwise.
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
                            self.log_info(f'Completed {action_info}')
                        else:
                            self.log_warning(f'Failed {action_info}: {action.activity_details}')

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
            self.log_info(f'Completed {log_context}')
        elif raise_on_failure:
            raise WaitActionsException(f'Failed {log_context}')
        else:
            self.log_warning(f'Failed {log_context}')

        return result


class TaskException(Exception):
    """ Exception for Task errors """
    pass


class WaitActionsException(TaskException):
    """ Exception indicating failure in one or more actions being monitored """
    pass


def chopper(section_size: int):
    section = {}
    for _ in range(section_size):
        data = yield
        if data is None:
            break
        primary_key, secondary_key, item = data
        section.setdefault(primary_key, {}).setdefault(secondary_key, []).append(item)
    return section


def request_details(secondary_dict: Mapping[str, Sequence[str]], devices_map: Mapping[str, str]) -> str:
    return ', '.join(
        f"{secondary_key} ({', '.join(devices_map.get(item) or item for item in item_list)})"
        for secondary_key, item_list in secondary_dict.items()
    )


def device_iter(api: Rest,
                match_name_regex: Optional[str] = None,
                match_reachable: bool = False,
                match_site_id: Optional[str] = None,
                match_system_ip: Optional[str] = None,
                default: Any = '-') -> Iterator[Tuple[str, str]]:
    """
    Return an iterator over device inventory, filtered by optional conditions.
    @param api: Instance of Rest API
    @param match_name_regex: Regular expression matching device host-name
    @param match_reachable: Boolean indicating whether to include reachable devices only
    @param match_site_id: When present, only include devices with provided site-id
    @param match_system_ip: If present, only include device with provided system-ip
    @param default: Optional default value used for Device iter absent fields
    @return: Iterator of (<device-uuid>, <device-name>) tuples.
    """
    return (
        (uuid, name)
        for uuid, name, system_ip, site_id, reachability, *_ in Device.get_raise(api).extended_iter(default=default)
        if (
            (match_name_regex is None or regex_search(match_name_regex, name)) and
            (not match_reachable or reachability == 'reachable') and
            (match_site_id is None or site_id == match_site_id) and
            (match_system_ip is None or system_ip == match_system_ip)
        )
    )


def clean_dir(target_dir_name: str, max_saved: int = 99) -> Union[str, bool]:
    """
    Clean target_dir_name directory if it exists. If max_saved is non-zero and target_dir_name exists, move it to a new
    directory name in sequence.
    @param target_dir_name: str with the directory to be cleaned
    @param max_saved: int indicating the maximum instances to keep. If 0, target_dir_name is just deleted.
    """
    target_dir = Path(DATA_DIR, target_dir_name)
    if target_dir.exists():
        if max_saved > 0:
            save_seq = range(max_saved)
            for elem in save_seq:
                save_path = Path(DATA_DIR, f'{target_dir_name}_{elem + 1}')
                if elem == save_seq[-1]:
                    rmtree(save_path, ignore_errors=True)
                if not save_path.exists():
                    target_dir.rename(save_path)
                    return save_path.name
        else:
            rmtree(target_dir, ignore_errors=True)

    return False


def export_json(table_iter: Iterable[Table], filename: str) -> None:
    """
    Export a group (Iterable) of Tables as a JSON encoded file
    @param table_iter: Tables to export
    @param filename: Name for the export file
    """
    with open(filename, 'w') as export_file:
        data = [table.dict() for table in table_iter]
        json.dump(data, export_file, indent=2)


def archive_create(archive_filename: str, workdir: str) -> None:
    """
    Create a zip archive with the contents of workdir
    @param archive_filename: zip archive filename
    @param workdir: a directory under DATA_DIR to be archived
    """
    source_dir = Path(DATA_DIR, workdir)
    with ZipFile(archive_filename, mode='w', compression=ZIP_DEFLATED) as archive_file:
        for member_path in source_dir.rglob("*"):
            archive_file.write(member_path, arcname=member_path.relative_to(source_dir))

    return


def archive_extract(archive_filename: str, workdir: str) -> None:
    """
    Extract zip archive into workdir
    @param archive_filename: zip archive filename
    @param workdir: a directory under DATA_DIR where to extract to
    """
    destination_dir = Path(DATA_DIR, workdir)
    with ZipFile(archive_filename, mode='r') as archive_file:
        archive_file.extractall(destination_dir)

    return
