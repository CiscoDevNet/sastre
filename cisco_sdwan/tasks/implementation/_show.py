import argparse
from typing import Any, NamedTuple, Union, Optional, Annotated
from collections.abc import Callable, Sequence
from pathlib import Path
from functools import partial
from concurrent import futures
from datetime import datetime, timedelta, timezone
from operator import attrgetter
from pydantic import field_validator, model_validator, Field
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import CATALOG_TAG_ALL, op_catalog_iter, OpType
from cisco_sdwan.base.models_base import (OperationalItem, RealtimeItem, BulkStatsItem, BulkStateItem, RecordItem,
                                          filename_safe)
from cisco_sdwan.base.models_vmanage import Device, Alarm, Event, get_device_type, DeviceType
from cisco_sdwan.tasks.utils import (regex_type, ipv4_type, site_id_type, filename_type, int_type, OpCmdOptions,
                                     TaskOptions, RTCmdSemantics, StateCmdSemantics, StatsCmdSemantics)
from cisco_sdwan.tasks.common import regex_search, Task, Table, get_table_filters, filtered_tables, export_json
from cisco_sdwan.tasks.models import TableTaskArgs, validate_op_cmd, const, IPv4AddressStr
from cisco_sdwan.tasks.validators import validate_site_id, validate_regex

THREAD_POOL_SIZE = 10
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


class DeviceInfo(NamedTuple):
    hostname: str
    system_ip: str
    site_id: str
    state: str
    device_type: str
    model: str


def retrieve_rt_task(api_obj: Rest, rt_cls: type[RealtimeItem], device: DeviceInfo) -> tuple[DeviceInfo, Any]:
    return device, rt_cls.get(api_obj, device.system_ip)


def table_fields(op_cls: type[OperationalItem], detail: bool, simple: bool) -> tuple:
    if detail and op_cls.fields_ext is not None:
        return op_cls.fields_std + op_cls.fields_ext

    if simple and op_cls.fields_sub is not None:
        return tuple(field for field in op_cls.fields_std if field not in op_cls.fields_sub)

    return op_cls.fields_std


@TaskOptions.register('show')
class TaskShow(Task):
    SAVINGS_FACTOR = 2
    STATS_AVG_INTERVAL_SECS = 300  # 5min window for statistics averages
    STATS_QUERY_RANGE_MINS = 120  # Statistics queries are from t to t - 2h

    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nShow task:')
        task_parser.prog = f'{task_parser.prog} show'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='show options')
        sub_tasks.required = True

        dev_parser = sub_tasks.add_parser('devices', aliases=['dev'], help='device list')
        dev_parser.set_defaults(subtask_handler=TaskShow.devices)
        dev_parser.set_defaults(subtask_info='devices')

        rt_parser = sub_tasks.add_parser('realtime', aliases=['rt'],
                                         help='realtime commands. Slower, but up-to-date data. vManage collect data '
                                              'from devices in realtime.')
        rt_parser.set_defaults(subtask_handler=TaskShow.realtime)
        rt_parser.set_defaults(subtask_info='realtime')

        state_parser = sub_tasks.add_parser('state', aliases=['st'],
                                            help='state commands. Faster and up-to-date synced state data.')
        state_parser.set_defaults(subtask_handler=TaskShow.bulk_state)
        state_parser.set_defaults(subtask_info='state')

        stats_parser = sub_tasks.add_parser('statistics', aliases=['stats'],
                                            help='statistics commands. Faster, but data is 30 min or more old. '
                                                 'Allows historical data queries.')
        stats_parser.set_defaults(subtask_handler=TaskShow.bulk_stats)
        stats_parser.set_defaults(subtask_info='statistics')
        stats_parser.add_argument('--days', metavar='<days>', type=partial(int_type, 0, 9999), default=0,
                                  help='query statistics from <days> ago (default: %(default)s, i.e. now)')
        stats_parser.add_argument('--hours', metavar='<hours>', type=partial(int_type, 0, 9999), default=0,
                                  help='query statistics from <hours> ago (default: %(default)s, i.e. now)')

        alarms_parser = sub_tasks.add_parser('alarms', help='display vManage alarms')
        alarms_parser.set_defaults(subtask_info='alarms')
        alarms_parser.set_defaults(subtask_op_cls=Alarm)

        events_parser = sub_tasks.add_parser('events', help='display vManage events')
        events_parser.set_defaults(subtask_info='events')
        events_parser.set_defaults(subtask_op_cls=Event)

        for sub_task, cmd_action, op_type in ((rt_parser, RTCmdSemantics, OpType.RT),
                                              (state_parser, StateCmdSemantics, OpType.STATE),
                                              (stats_parser, StatsCmdSemantics, OpType.STATS)):
            sub_task.add_argument('cmd', metavar='<cmd>', nargs='+', action=cmd_action,
                                  help='group of, or specific command to execute. '
                                       f'Group options: {OpCmdOptions.tags(op_type)}. '
                                       f'Command options: {OpCmdOptions.commands(op_type)}. '
                                       f'Group "{CATALOG_TAG_ALL}" selects all commands.')

        for sub_task in (rt_parser, state_parser, stats_parser, dev_parser):
            mutex = sub_task.add_mutually_exclusive_group()
            mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='select devices matching regular expression on device name or model.')
            mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                               help='select devices NOT matching regular expression on device name or model.')
            sub_task.add_argument('--reachable', action='store_true', help='select devices that are reachable')
            sub_task.add_argument('--site', metavar='<id>', type=site_id_type, help='select devices with site ID')
            sub_task.add_argument('--system-ip', nargs='+', metavar='<ipv4>', type=ipv4_type,
                                  help='select devices with system IP')
            sub_task.add_argument('--device-type', choices=[d_type.value for d_type in DeviceType],
                                  help='select devices of specific type')

        for sub_task in (alarms_parser, events_parser):
            sub_task.set_defaults(subtask_handler=TaskShow.records)
            sub_task.add_argument('--max', metavar='<max-records>', type=partial(int_type, 1, 999999), default=100,
                                  help='maximum number records to retrieve (default: %(default)s)')
            sub_task.add_argument('--days', metavar='<days>', type=partial(int_type, 0, 9999), default=0,
                                  help='retrieve records since <days> ago (default: %(default)s)')
            sub_task.add_argument('--hours', metavar='<hours>', type=partial(int_type, 0, 9999), default=1,
                                  help='retrieve records since <hours> ago (default: %(default)s)')

        for sub_task in (rt_parser, state_parser, stats_parser, alarms_parser, events_parser):
            mutex = sub_task.add_mutually_exclusive_group()
            mutex.add_argument('--detail', action='store_true', help='detailed output (i.e. more columns)')
            mutex.add_argument('--simple', action='store_true', help='simple output (i.e. less columns)')

        for sub_task in (rt_parser, state_parser, stats_parser, dev_parser, alarms_parser, events_parser):
            sub_task.add_argument('--exclude', metavar='<regex>', type=regex_type,
                                  help='exclude table rows matching the regular expression')
            sub_task.add_argument('--include', metavar='<regex>', type=regex_type,
                                  help='include table rows matching the regular expression, exclude all other rows')
            sub_task.add_argument('--save-csv', metavar='<directory>', type=filename_type,
                                  help='export results as CSV files under the specified directory')
            sub_task.add_argument('--save-json', metavar='<filename>', type=filename_type,
                                  help='export results as JSON-formatted file')

        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info(f'Show {parsed_args.subtask_info} task: vManage URL: "{api.base_url}"')

        filters = get_table_filters(exclude_regex=parsed_args.exclude, include_regex=parsed_args.include)
        result_tables = filtered_tables(parsed_args.subtask_handler(self, parsed_args, api), *filters)

        if not result_tables:
            return

        if parsed_args.save_csv is not None:
            Path(parsed_args.save_csv).mkdir(parents=True, exist_ok=True)
            for table in result_tables:
                filename_tokens = [parsed_args.subtask_info]
                if table.name is not None:
                    filename_tokens.append(filename_safe(table.name, lower=True).replace(' ', '_'))
                table.save(Path(parsed_args.save_csv, f"{'_'.join(filename_tokens)}.csv"))
            self.log_info(f"Tables exported as CSV files under directory '{parsed_args.save_csv}'")

        if parsed_args.save_json is not None:
            export_json(result_tables, parsed_args.save_json)
            self.log_info(f"Tables exported as JSON file '{parsed_args.save_json}'")

        return result_tables if (parsed_args.save_csv is None and parsed_args.save_json is None) else None

    def realtime(self, parsed_args, api: Rest) -> list[Table]:
        devices = self.selected_devices(parsed_args, api)
        pool_size = max(min(len(devices), THREAD_POOL_SIZE), 1)

        result_tables = []
        for info, rt_cls in op_catalog_iter(OpType.RT, *parsed_args.cmd, version=api.server_version):
            devices_in_scope = [dev_info for dev_info in devices if rt_cls.is_in_scope(dev_info.model)]
            if not devices_in_scope:
                self.log_debug(f"Skipping {info.lower()}, not applicable to any of the devices selected")
                continue

            self.log_info(f'Retrieving {info.lower()} for {len(devices_in_scope)} devices')
            with futures.ThreadPoolExecutor(pool_size) as executor:
                job_result_iter = executor.map(partial(retrieve_rt_task, api, rt_cls), devices_in_scope)

            table = None
            fields = table_fields(rt_cls, parsed_args.detail, parsed_args.simple)
            for device, rt_obj in job_result_iter:
                if rt_obj is None:
                    self.log_error(f'Failed to retrieve {info.lower()} from {device.hostname}')
                    continue

                if table is None:
                    table = Table('Device', *rt_obj.field_info(*fields), name=info)

                table.extend(
                    (device.hostname, *row_values)
                    for row_values in sorted(rt_obj.field_value_iter(*fields, **rt_cls.field_conversion_fns))
                )
                table.add_marker()

            if table:
                result_tables.append(table)

        return result_tables

    def bulk_state(self, parsed_args, api: Rest) -> list[Table]:
        devices = self.selected_devices(parsed_args, api)

        result_tables = []
        for info, op_cls in op_catalog_iter(OpType.STATE, *parsed_args.cmd, version=api.server_version):
            self.log_info(f'Retrieving {info.lower()} for {len(devices)} devices')

            op_obj: BulkStateItem = op_cls.get(api, count=10000)
            if op_obj is None:
                self.log_error(f'Failed to retrieve {info.lower()}')
                continue

            fields = table_fields(op_cls, parsed_args.detail, parsed_args.simple)
            node_data_dict = {}
            for node_id, *node_data_sample in op_obj.field_value_iter(
                    op_cls.field_node_id, *fields, **op_cls.field_conversion_fns):
                node_data_dict.setdefault(node_id, []).append(node_data_sample)

            table = self.build_table(info, op_obj.field_info(*fields), devices, node_data_dict)
            if table:
                result_tables.append(table)

        return result_tables

    def bulk_stats(self, parsed_args, api: Rest) -> list[Table]:
        devices = self.selected_devices(parsed_args, api)
        end_time = datetime.now(tz=timezone.utc) - timedelta(days=parsed_args.days, hours=parsed_args.hours)
        start_time = end_time - timedelta(minutes=self.STATS_QUERY_RANGE_MINS)
        query_params = {
            "endDate": end_time.strftime(TIME_FORMAT),
            "startDate": start_time.strftime(TIME_FORMAT),
            "count": 10000,
            "timeZone": "UTC"
        }
        self.log_info(f'Query timestamp: {end_time:%Y-%m-%d %H:%M:%S %Z}')

        result_tables = []
        for info, op_cls in op_catalog_iter(OpType.STATS, *parsed_args.cmd, version=api.server_version):
            self.log_info(f'Retrieving {info.lower()} for {len(devices)} devices')

            op_obj: BulkStatsItem = op_cls.get(api, **query_params)
            if op_obj is None:
                self.log_error(f'Failed to retrieve {info.lower()}')
                continue

            fields = table_fields(op_cls, parsed_args.detail, parsed_args.simple)
            node_data_dict = {}
            for node_id, *node_data_sample in op_obj.aggregated_value_iter(
                    self.STATS_AVG_INTERVAL_SECS, op_cls.field_node_id, *fields, **op_cls.field_conversion_fns):
                node_data_dict.setdefault(node_id, []).append(node_data_sample)

            table = self.build_table(info, op_obj.field_info(*fields), devices, node_data_dict)
            if table:
                result_tables.append(table)

        return result_tables

    def devices(self, parsed_args, api: Rest) -> list[Table]:
        devices = self.selected_devices(parsed_args, api)

        result_tables = []
        table = Table('Name', 'System IP', 'Site ID', 'Reachability', 'Type', 'Model')
        table.extend(devices)
        if table:
            result_tables.append(table)

        return result_tables

    def selected_devices(self, parsed_args, api: Rest) -> list[DeviceInfo]:
        regex = parsed_args.regex or parsed_args.not_regex
        matched_items = [
            DeviceInfo(name, system_ip, site_id, state, get_device_type(d_type, model), model)
            for _, name, system_ip, site_id, state, d_type, model in Device.get_raise(api).extended_iter(default='-')
            if ((regex is None or regex_search(regex, name, model, inverse=parsed_args.regex is None)) and
                (not parsed_args.reachable or state == 'reachable') and
                (parsed_args.site is None or site_id == parsed_args.site) and
                (parsed_args.system_ip is None or system_ip in parsed_args.system_ip) and
                (parsed_args.device_type is None or get_device_type(d_type, model) == parsed_args.device_type))
        ]
        # Sort device list by hostname then system ip
        matched_items.sort(key=attrgetter('hostname', 'system_ip'))

        self.log_info(f'Device selection matched {len(matched_items)} devices')
        return matched_items

    def build_table(self, name: str, headers: Sequence[str], devices: Sequence[DeviceInfo], device_data: dict) -> Table:
        table = Table('Device', *headers, name=name)
        for device in devices:
            device_row_values = device_data.get(device.system_ip)
            if device_row_values is None:
                self.log_info(f'{name} missing for {device.hostname}')
                continue

            # Row values are sorted to ensure consistent output
            device_row_values.sort()
            table.extend((device.hostname, *row_values) for row_values in device_row_values)
            table.add_marker()

        return table

    def records(self, parsed_args, api: Rest) -> list[Table]:
        device_map = {system_ip: name for _, name, system_ip, *_ in Device.get_raise(api).extended_iter(default='-')}

        def device_names(devices_field):
            system_ips = (entry.get('system-ip', '') for entry in devices_field)
            return ', '.join(device_map.get(system_ip, system_ip) for system_ip in system_ips)

        end_time = datetime.now(tz=timezone.utc)
        start_time = end_time - timedelta(days=parsed_args.days, hours=parsed_args.hours)
        self.log_info(f'Records query: {start_time:%Y-%m-%d %H:%M:%S %Z} -> {end_time:%Y-%m-%d %H:%M:%S %Z}')

        result_tables = []
        op_obj: RecordItem = parsed_args.subtask_op_cls.get(api, start_time=start_time, end_time=end_time,
                                                            max_records=parsed_args.max)
        if op_obj is None:
            self.log_error(f'Failed to retrieve {parsed_args.subtask_info.lower()}')
        else:
            fields = table_fields(parsed_args.subtask_op_cls, parsed_args.detail, parsed_args.simple)
            field_conversion_fns = {**op_obj.field_conversion_fns, 'devices': device_names}
            table = Table(*op_obj.field_info(*fields))
            table.extend(row for row in op_obj.field_value_iter(*fields, **field_conversion_fns))

            if table:
                result_tables.append(table)

        return result_tables


class ShowArgs(TableTaskArgs):
    subtask_info: str
    subtask_handler: Callable
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    reachable: bool = False
    site: Optional[str] = None
    system_ip: Optional[list[IPv4AddressStr]] = None
    device_type: Optional[DeviceType] = None

    # Validators
    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)
    _validate_site_id = field_validator('site')(validate_site_id)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'ShowArgs':
        if self.regex is not None and self.not_regex is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        if getattr(self, 'detail', False) and getattr(self, 'simple', False):
            raise ValueError('Argument "detail" not allowed with "simple"')

        return self


class ShowDevicesArgs(ShowArgs):
    subtask_info: const(str, 'devices')
    subtask_handler: const(Callable, TaskShow.devices)


class ShowRealtimeArgs(ShowArgs):
    subtask_info: const(str, 'realtime')
    subtask_handler: const(Callable, TaskShow.realtime)
    cmd: list[str]
    detail: bool = False
    simple: bool = False

    # Validators
    @field_validator('cmd')
    @classmethod
    def validate_cmd(cls, cmd_list: list[str]) -> list[str]:
        return validate_op_cmd(OpType.RT, cmd_list)


class ShowStateArgs(ShowArgs):
    subtask_info: const(str, 'state')
    subtask_handler: const(Callable, TaskShow.bulk_state)
    cmd: list[str]
    detail: bool = False
    simple: bool = False

    # Validators
    @field_validator('cmd')
    @classmethod
    def validate_cmd(cls, cmd_list: list[str]) -> list[str]:
        return validate_op_cmd(OpType.STATE, cmd_list)


class ShowStatisticsArgs(ShowArgs):
    subtask_info: const(str, 'statistics')
    subtask_handler: const(Callable, TaskShow.bulk_stats)
    cmd: list[str]
    detail: bool = False
    simple: bool = False
    days: Annotated[int, Field(ge=0, lt=10000)] = 0
    hours: Annotated[int, Field(ge=0, lt=10000)] = 0

    # Validators
    @field_validator('cmd')
    @classmethod
    def validate_cmd(cls, cmd_list: list[str]) -> list[str]:
        return validate_op_cmd(OpType.STATS, cmd_list)


class ShowRecordsArgs(TableTaskArgs):
    subtask_info: str
    subtask_handler: const(Callable, TaskShow.records)
    subtask_op_cls: Callable
    max: Annotated[int, Field(ge=1, lt=1000000)] = 100
    days: Annotated[int, Field(ge=0, lt=10000)] = 0
    hours: Annotated[int, Field(ge=0, lt=10000)] = 1
    detail: bool = False
    simple: bool = False

    @model_validator(mode='after')
    def mutex_validations(self) -> 'ShowRecordsArgs':
        if getattr(self, 'detail', False) and getattr(self, 'simple', False):
            raise ValueError('Argument "detail" not allowed with "simple"')

        return self


class ShowAlarmsArgs(ShowRecordsArgs):
    subtask_info: const(str, 'alarms')
    subtask_op_cls: const(Callable, Alarm)


class ShowEventsArgs(ShowRecordsArgs):
    subtask_info: const(str, 'events')
    subtask_op_cls: const(Callable, Event)
