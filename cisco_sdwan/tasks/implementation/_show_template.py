import argparse
from pathlib import Path
from collections import namedtuple
from typing import List, Union, Optional, Callable
from operator import itemgetter, attrgetter
from pydantic import validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import RestAPIException, Rest
from cisco_sdwan.base.catalog import catalog_iter
from cisco_sdwan.base.models_base import filename_safe
from cisco_sdwan.base.models_vmanage import (DeviceTemplate, DeviceTemplateAttached, DeviceTemplateValues,
                                             DeviceTemplateIndex, FeatureTemplate, FeatureTemplateIndex)
from cisco_sdwan.tasks.utils import TaskOptions, existing_workdir_type, filename_type, regex_type
from cisco_sdwan.tasks.common import regex_search, Task, Table, get_table_filters, filtered_tables, export_json
from cisco_sdwan.tasks.models import TableTaskArgs, const
from cisco_sdwan.tasks.validators import validate_workdir, validate_regex


@TaskOptions.register('show-template')
class TaskShowTemplate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nShow-template task:')
        task_parser.prog = f'{task_parser.prog} show-template'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='show-template options')
        sub_tasks.required = True

        values_parser = sub_tasks.add_parser('values', help='show values from template attachments')
        values_parser.set_defaults(subtask_handler=TaskShowTemplate.values_table)
        values_parser.set_defaults(subtask_info='values')
        values_parser.add_argument('--templates', metavar='<regex>', type=regex_type,
                                   help='regular expression selecting device templates to inspect. '
                                        'Match on template name or ID.')

        refs_parser = sub_tasks.add_parser('references', aliases=['ref'],
                                           help='show device templates that reference a feature template')
        refs_parser.set_defaults(subtask_handler=TaskShowTemplate.references_table)
        refs_parser.set_defaults(subtask_info='references')
        refs_parser.add_argument('--with-refs', action='store_true',
                                 help='include only feature-templates with device-template references')
        refs_parser.add_argument('--templates', metavar='<regex>', type=regex_type,
                                 help='regular expression matching feature template names to include')

        # Parameters common to all sub-tasks
        for sub_task in (values_parser, refs_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                  help='show-template will read from the specified directory instead of target vManage')
            sub_task.add_argument('--exclude', metavar='<regex>', type=regex_type,
                                  help='exclude table rows matching the regular expression')
            sub_task.add_argument('--include', metavar='<regex>', type=regex_type,
                                  help='include table rows matching the regular expression, exclude all other rows')
            sub_task.add_argument('--save-csv', metavar='<directory>', type=filename_type,
                                  help='export tables as CSV files under the specified directory')
            sub_task.add_argument('--save-json', metavar='<filename>', type=filename_type,
                                  help='export results as JSON-formatted file')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args) -> bool:
        return parsed_args.workdir is None

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info(f'Show-template {parsed_args.subtask_info} task: {source_info}')

        filters = get_table_filters(exclude_regex=parsed_args.exclude, include_regex=parsed_args.include)
        result_tables = filtered_tables(parsed_args.subtask_handler(self, parsed_args, api), *filters)

        if not result_tables:
            self.log_warning('No results found')
            return

        if parsed_args.save_csv is not None:
            Path(parsed_args.save_csv).mkdir(parents=True, exist_ok=True)
            for table in result_tables:
                table.save(Path(parsed_args.save_csv, table.meta))
            self.log_info(f"Tables exported as CSV files under directory '{parsed_args.save_csv}'")

        if parsed_args.save_json is not None:
            export_json(result_tables, parsed_args.save_json)
            self.log_info(f"Tables exported as JSON file '{parsed_args.save_json}'")

        return result_tables if (parsed_args.save_csv is None and parsed_args.save_json is None) else None

    def values_table(self, parsed_args, api: Optional[Rest]) -> List[Table]:
        def template_values(ext_name: bool, template_name: str, template_id: str) -> Union[DeviceTemplateValues, None]:
            if api is None:
                # Load from local backup
                values = DeviceTemplateValues.load(parsed_args.workdir, ext_name, template_name, template_id)
                if values is None:
                    self.log_debug(f'Skipped {template_name}. No template values file found.')
            else:
                # Load from vManage via API
                devices_attached = DeviceTemplateAttached.get(api, template_id)
                if devices_attached is None:
                    self.log_error(f'Failed to retrieve {template_name} attached devices')
                    return None

                try:
                    uuid_list = [uuid for uuid, _ in devices_attached]
                    values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(template_id, uuid_list),
                                                           DeviceTemplateValues.api_path.post))
                except RestAPIException:
                    self.log_error(f'Failed to retrieve {template_name} values')
                    return None

            return values

        # Templates are sorted by template name then ID. Then for each template with attachments, devices are sorted
        # by name then UUID. The values for each device are sorted by the variable name
        result_tables = []
        backend = api or parsed_args.workdir
        matched_templates = [
            (item_id, item_name, index.need_extended_name, tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter('template_device'))
            for item_id, item_name in index
            if (issubclass(item_cls, DeviceTemplate) and
                (parsed_args.templates is None or regex_search(parsed_args.templates, item_name, item_id)))
        ]
        matched_templates.sort(key=itemgetter(1, 0))
        for item_id, item_name, use_ext_name, tag, info in matched_templates:
            attached_values = template_values(use_ext_name, item_name, item_id)
            if attached_values is None:
                continue

            self.log_info(f'Inspecting {info} {item_name} values')
            var_names = attached_values.title_dict()
            for csv_id, csv_name, entry in sorted(attached_values, key=itemgetter(1, 0)):
                table = Table('Name', 'Value', 'Variable',
                              name=f"Template {item_name}, device {csv_name or csv_id}",
                              meta=f"template_values_{filename_safe(item_name, lower=True)}_{csv_name or csv_id}.csv")
                table.extend(
                    (var_names.get(var, '<not found>'), value, var)
                    for var, value in sorted(entry.items(), key=itemgetter(0))
                )
                if table:
                    result_tables.append(table)

        return result_tables

    def references_table(self, parsed_args, api: Optional[Rest]) -> List[Table]:
        FeatureInfo = namedtuple('FeatureInfo', ['name', 'type', 'attached', 'device_templates'])

        backend = api or parsed_args.workdir
        self.log_info('Inspecting feature templates')
        feature_index = self.index_get(FeatureTemplateIndex, backend)
        feature_dict = {}
        for item_id, item_name in feature_index:
            feature = self.item_get(FeatureTemplate, backend, item_id, item_name, feature_index.need_extended_name)
            if feature is None:
                self.log_error(f'Failed to load feature template {item_name}')
                continue

            feature_dict[item_id] = FeatureInfo(item_name, feature.type, feature.devices_attached, set())

        self.log_info('Inspecting device templates')
        device_index = self.index_get(DeviceTemplateIndex, backend)
        for item_id, item_name in device_index:
            device = self.item_get(DeviceTemplate, backend, item_id, item_name, device_index.need_extended_name)
            if device is None:
                self.log_error(f'Failed to load device template {item_name}')
                continue
            if device.is_type_cli:
                continue

            for feature_id in device.feature_templates:
                feature_info = feature_dict.get(feature_id)
                if feature_info is None:
                    self.log_warning(f'Template {item_name} references a missing feature template: {feature_id}')
                    continue

                feature_info.device_templates.add(item_name)

        self.log_info('Creating references table')
        # Ordered by feature template name. Then device templates are sorted by template name.
        table = Table('Feature Template', 'Type', 'Devices Attached', 'Device Templates',
                      meta="template_references.csv")
        matched_feature_templates = [
            info for info in feature_dict.values()
            if parsed_args.templates is None or regex_search(parsed_args.templates, info.name)
        ]
        matched_feature_templates.sort(key=attrgetter('name'))
        for feature_info in matched_feature_templates:
            if not parsed_args.with_refs and not feature_info.device_templates:
                table.add_marker()
                table.add(feature_info.name, feature_info.type, str(feature_info.attached), '')
                continue

            is_first = True
            for device_template in sorted(feature_info.device_templates):
                if is_first:
                    table.add_marker()
                    table.add(feature_info.name, feature_info.type, str(feature_info.attached), device_template)
                    is_first = False
                else:
                    table.add('', '', '', device_template)

        result_tables = []
        if table:
            result_tables.append(table)

        return result_tables


class ShowTemplateArgs(TableTaskArgs):
    subtask_info: str
    subtask_handler: Callable
    workdir: Optional[str] = None
    templates: Optional[str] = None

    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)
    _validate_templates = validator('templates', allow_reuse=True)(validate_regex)


class ShowTemplateValuesArgs(ShowTemplateArgs):
    subtask_info: str = const('values')
    subtask_handler: Callable = const(TaskShowTemplate.values_table)


class ShowTemplateRefArgs(ShowTemplateArgs):
    subtask_info: str = const('references')
    subtask_handler: Callable = const(TaskShowTemplate.references_table)
    with_refs: bool = False
