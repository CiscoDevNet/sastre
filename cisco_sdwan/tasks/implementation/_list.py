import argparse
from typing import Union, Optional
from collections.abc import Callable
from operator import itemgetter
from functools import partial
from pydantic import model_validator, field_validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL
from cisco_sdwan.base.models_base import ExtendedTemplate
from cisco_sdwan.base.models_vmanage import EdgeCertificate
from cisco_sdwan.tasks.models import TableTaskArgs, CatalogTag, const
from cisco_sdwan.tasks.utils import (TaskOptions, TagOptions, existing_workdir_type, filename_type, regex_type,
                                     ext_template_type)
from cisco_sdwan.tasks.common import regex_filter, Task, Table, get_table_filters, export_json
from cisco_sdwan.tasks.validators import validate_workdir, validate_ext_template, validate_regex


@TaskOptions.register('list')
class TaskList(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nList task:')
        task_parser.prog = f'{task_parser.prog} list'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='list options')
        sub_tasks.required = True

        config_parser = sub_tasks.add_parser('configuration', aliases=['config'], help='list configuration items')
        config_parser.set_defaults(subtask_handler=TaskList.config_table)
        config_parser.set_defaults(subtask_info='configuration')
        config_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                   help='one or more tags for selecting groups of items. Multiple tags should be '
                                        f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                        f'"{CATALOG_TAG_ALL}" selects all items.')

        cert_parser = sub_tasks.add_parser('certificate', aliases=['cert'], help='list device certificate information')
        cert_parser.set_defaults(subtask_handler=TaskList.cert_table)
        cert_parser.set_defaults(subtask_info='certificate')

        xform_parser = sub_tasks.add_parser('transform',
                                            help='list name transformations performed by a name-regex against '
                                                 'existing item names')
        xform_parser.set_defaults(subtask_handler=TaskList.xform_table)
        xform_parser.set_defaults(subtask_info='transform')
        xform_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                  help='one or more tags for selecting groups of items. Multiple tags should be '
                                       f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                       f'"{CATALOG_TAG_ALL}" selects all items.')
        xform_parser.add_argument('name_regex', metavar='<name-regex>', type=ext_template_type,
                                  help='name-regex used to transform an existing item name. Variable {name} is '
                                       'replaced with the original template name. Sections of the original template '
                                       'name can be selected using the {name <regex>} format. Where <regex> is a '
                                       'regular expression that must contain at least one capturing group. Capturing '
                                       'groups identify sections of the original name to keep.')
        xform_mutex = xform_parser.add_mutually_exclusive_group()
        xform_mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='select items matching regular expression on their original names')
        xform_mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                                 help='select items NOT matching regular expression on their original item names')

        # Parameters common to all sub-tasks
        for sub_task in (config_parser, cert_parser, xform_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                  help='list will read from the specified directory instead of target vManage')
            sub_task.add_argument('--exclude', metavar='<regex>', type=regex_type,
                                  help='exclude table rows matching the regular expression')
            sub_task.add_argument('--include', metavar='<regex>', type=regex_type,
                                  help='include table rows matching the regular expression, exclude all other rows')
            sub_task.add_argument('--save-csv', metavar='<filename>', type=filename_type,
                                  help='export table as CSV-formatted file')
            sub_task.add_argument('--save-json', metavar='<filename>', type=filename_type,
                                  help='export table as JSON-formatted file')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args) -> bool:
        return parsed_args.workdir is None

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info(f'List {parsed_args.subtask_info} task: {source_info}')

        result_table: Table = parsed_args.subtask_handler(self, parsed_args, api)

        filters = get_table_filters(exclude_regex=parsed_args.exclude, include_regex=parsed_args.include)
        result_table = result_table.filtered(*filters)
        self.log_info(f'Selection matched {len(result_table)} items')

        if not result_table:
            return

        if parsed_args.save_csv is not None:
            result_table.save(parsed_args.save_csv)
            self.log_info(f"Table exported as CSV file '{parsed_args.save_csv}'")

        if parsed_args.save_json is not None:
            export_json([result_table], parsed_args.save_json)
            self.log_info(f"Table exported as JSON file '{parsed_args.save_json}'")

        return [result_table] if (parsed_args.save_csv is None and parsed_args.save_json is None) else None

    def config_table(self, parsed_args, api: Optional[Rest]) -> Table:
        self.log_debug("Starting configuration subtask")
        backend = api or parsed_args.workdir
        # Only perform version-based filtering if backend is api
        version = None if api is None else api.server_version

        # Within each tag, table entries are sorted by item_name then item_id. Tag order is defined by the catalog.
        table = Table('Name', 'ID', 'Tag', 'Type')
        table.extend(
            (item_name, item_id, tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter(*parsed_args.tags, version=version))
            for item_id, item_name in sorted(index, key=itemgetter(1, 0))
        )

        return table

    def cert_table(self, parsed_args, api: Optional[Rest]) -> Table:
        self.log_debug("Starting certificate subtask")
        if api is None:
            certs = EdgeCertificate.load(parsed_args.workdir)
            if certs is None:
                raise FileNotFoundError('WAN edge certificates were not found in the backup')
        else:
            certs = EdgeCertificate.get_raise(api)

        # Table will be sorted by hostname then chassis
        table = Table('Hostname', 'Chassis', 'Serial', 'State', 'Status')
        matched_items = [
            (hostname, chassis, serial, EdgeCertificate.state_str(state), status)
            for uuid, status, hostname, chassis, serial, state in certs.extended_iter(default='-')
        ]
        matched_items.sort(key=itemgetter(0, 1))
        table.extend(matched_items)

        return table

    def xform_table(self, parsed_args, api: Optional[Rest]) -> Table:
        self.log_debug("Starting transform subtask")
        backend = api or parsed_args.workdir
        # Only perform version-based filtering if backend is api
        version = None if api is None else api.server_version

        name_regex = ExtendedTemplate(parsed_args.name_regex)

        regex_filter_fn = partial(regex_filter, parsed_args.regex, parsed_args.not_regex)

        # Within a given tag, table entries are sorted by item_name. Tag order is defined by the catalog
        table = Table('Name', 'Transformed', 'Tag', 'Type')
        matched_items = [
            (item_name, name_regex(item_name), tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter(*parsed_args.tags, version=version))
            for item_id, item_name in index
            if regex_filter_fn(item_name)
        ]
        matched_items.sort(key=itemgetter(0))
        table.extend(matched_items)

        return table


class ListArgs(TableTaskArgs):
    subtask_info: str
    subtask_handler: Callable
    workdir: Optional[str] = None

    # Validators
    _validate_workdir = field_validator('workdir')(validate_workdir)


class ListConfigArgs(ListArgs):
    subtask_info: const(str, 'configuration')
    subtask_handler: const(Callable, TaskList.config_table)
    tags: list[CatalogTag]


class ListCertificateArgs(ListArgs):
    subtask_info: const(str, 'certificate')
    subtask_handler: const(Callable, TaskList.cert_table)


class ListTransformArgs(ListArgs):
    subtask_info: const(str, 'transform')
    subtask_handler: const(Callable, TaskList.xform_table)
    tags: list[CatalogTag]
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    name_regex: str

    # Validators
    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)
    _validate_name_regex = field_validator('name_regex')(validate_ext_template)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'ListTransformArgs':
        if self.regex is not None and self.not_regex is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return self
