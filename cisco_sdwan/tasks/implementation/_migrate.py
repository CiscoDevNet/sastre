import argparse
from typing import Union, Optional
from uuid import uuid4
from contextlib import suppress
from pydantic import validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import update_ids, ServerInfo, ExtendedTemplate
from cisco_sdwan.base.models_vmanage import DeviceTemplate, FeatureTemplate
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.migration import factory_cedge_aaa, factory_cedge_global
from cisco_sdwan.migration.feature_migration import FeatureProcessor
from cisco_sdwan.migration.device_migration import DeviceProcessor
from cisco_sdwan.tasks.utils import TaskOptions, existing_workdir_type, filename_type, version_type, ext_template_type
from cisco_sdwan.tasks.common import clean_dir, Task, TaskException
from cisco_sdwan.tasks.models import TaskArgs
from cisco_sdwan.tasks.validators import validate_workdir, validate_ext_template, validate_version, validate_filename


@TaskOptions.register('migrate')
class TaskMigrate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nMigrate task:')
        task_parser.prog = f'{task_parser.prog} migrate'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('scope', choices=['all', 'attached'],
                                 help='select whether to evaluate all feature templates, or only feature templates '
                                      'attached to device templates.')
        task_parser.add_argument('output', metavar='<directory>', type=filename_type,
                                 help='directory to save migrated templates')
        task_parser.add_argument('--no-rollover', action='store_true',
                                 help='by default, if the output directory already exists it is renamed using a '
                                      'rolling naming scheme. This option disables this automatic rollover.')
        task_parser.add_argument('--name', metavar='<name-regex>', type=ext_template_type, default='migrated_{name}',
                                 help='name-regex used to name the migrated templates (default: %(default)s). '
                                      'Variable {name} is replaced with the original template name. Sections of the '
                                      'original template name can be selected using the {name <regex>} syntax. Where '
                                      '<regex> is a regular expression that must contain at least one capturing group. '
                                      'Capturing groups identify sections of the original name to keep.')
        task_parser.add_argument('--from', metavar='<version>', type=version_type, dest='from_version', default='18.4',
                                 help='vManage version from source templates (default: %(default)s)')
        task_parser.add_argument('--to', metavar='<version>', type=version_type, dest='to_version', default='20.1',
                                 help='target vManage version for template migration (default: %(default)s)')
        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                 help='migrate will read from the specified directory instead of target vManage')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args) -> bool:
        return parsed_args.workdir is None

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info('Migrate task: %s %s -> %s Local output dir: "%s"', source_info, parsed_args.from_version,
                      parsed_args.to_version, parsed_args.output)

        # Output directory must be empty for a new migration
        saved_output = clean_dir(parsed_args.output, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_output:
            self.log_info('Previous migration under "%s" was saved as "%s"', parsed_args.output, saved_output)

        if api is None:
            backend = parsed_args.workdir
            local_info = ServerInfo.load(backend)
            server_version = local_info.server_version if local_info is not None else None
        else:
            backend = api
            server_version = backend.server_version

        try:
            # Load migration processors
            loaded_processors = {
                FeatureTemplate: FeatureProcessor.load(from_version=parsed_args.from_version,
                                                       to_version=parsed_args.to_version),
                DeviceTemplate: DeviceProcessor.load(from_version=parsed_args.from_version,
                                                     to_version=parsed_args.to_version)
            }
            self.log_info('Loaded template migration recipes')

            server_info = ServerInfo(server_version=parsed_args.to_version)
            if server_info.save(parsed_args.output):
                self.log_info('Saved vManage server information')

            id_mapping = {}  # {<old_id>: <new_id>}
            for tag in ordered_tags(CATALOG_TAG_ALL, reverse=True):
                self.log_info('Inspecting %s items', tag)

                for _, info, index_cls, item_cls in catalog_iter(tag, version=server_version):
                    item_index = self.index_get(index_cls, backend)
                    if item_index is None:
                        self.log_debug('Skipped %s, none found', info)
                        continue

                    name_set = {item_name for item_id, item_name in item_index}

                    is_bad_name = False
                    export_list = []
                    id_hint_map = {item_name: item_id for item_id, item_name in item_index}
                    for item_id, item_name in item_index:
                        item = self.item_get(item_cls, backend, item_id, item_name, item_index.need_extended_name)
                        if item is None:
                            self.log_error('Failed loading %s %s', info, item_name)
                            continue

                        with suppress(StopProcessorException):
                            item_processor = loaded_processors.get(item_cls)
                            if item_processor is None:
                                raise StopProcessorException()

                            self.log_debug('Evaluating %s %s', info, item_name)
                            if not item_processor.is_in_scope(item, migrate_all=(parsed_args.scope == 'all')):
                                self.log_debug('Skipping %s, migration not necessary', item_name)
                                raise StopProcessorException()

                            new_name = ExtendedTemplate(parsed_args.name)(item_name)
                            if not item_cls.is_name_valid(new_name):
                                self.log_error('New %s name is not valid: %s', info, new_name)
                                is_bad_name = True
                                raise StopProcessorException()
                            if new_name in name_set:
                                self.log_error('New %s name collision: %s -> %s', info, item_name, new_name)
                                is_bad_name = True
                                raise StopProcessorException()

                            name_set.add(new_name)

                            new_id = str(uuid4())
                            new_payload, trace_log = item_processor.eval(item, new_name, new_id)
                            for trace in trace_log:
                                self.log_debug('Processor: %s', trace)

                            if item.is_equal(new_payload):
                                self.log_debug('Skipping %s, no changes', item_name)
                                raise StopProcessorException()

                            new_item = item_cls(update_ids(id_mapping, new_payload))
                            id_mapping[item_id] = new_id
                            id_hint_map[new_name] = new_id

                            if item_processor.replace_original():
                                self.log_debug('Migrated replaces original: %s -> %s', item_name, new_name)
                                item = new_item
                            else:
                                self.log_debug('Migrated adds to original: %s + %s', item_name, new_name)
                                export_list.append(new_item)

                        export_list.append(item)

                    if is_bad_name:
                        raise TaskException(f'One or more new {info} names are not valid')

                    if not export_list:
                        self.log_info('No %s migrated', info)
                        continue

                    if issubclass(item_cls, FeatureTemplate):
                        for factory_default in (factory_cedge_aaa, factory_cedge_global):
                            if any(factory_default.name == elem.name for elem in export_list):
                                self.log_debug('Using existing factory %s %s', info, factory_default.name)
                                # Updating because device processor always use the built-in IDs
                                id_mapping[factory_default.uuid] = id_hint_map[factory_default.name]
                            else:
                                export_list.append(factory_default)
                                id_hint_map[factory_default.name] = factory_default.uuid
                                self.log_debug('Added factory %s %s', info, factory_default.name)

                    new_item_index = index_cls.create(export_list, id_hint_map)
                    if new_item_index.save(parsed_args.output):
                        self.log_info('Saved %s index', info)

                    for new_item in export_list:
                        if new_item.save(parsed_args.output, new_item_index.need_extended_name, new_item.name,
                                         id_hint_map[new_item.name]):
                            self.log_info('Saved %s %s', info, new_item.name)

        except (ProcessorException, TaskException) as ex:
            self.log_critical('Migration aborted: %s', ex)

        return


class MigrateArgs(TaskArgs):
    scope: str
    output: str
    no_rollover: bool = False
    name: str = 'migrated_{name}'
    from_version: str = '18.4'
    to_version: str = '20.1'
    workdir: Optional[str] = None

    # Validators
    _validate_filename = validator('output', allow_reuse=True)(validate_filename)
    _validate_name = validator('name', allow_reuse=True)(validate_ext_template)
    _validate_version = validator('from_version', 'to_version', allow_reuse=True)(validate_version)
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)

    @validator('scope')
    def validate_scope(cls, v):
        scope_options = ('all', 'attached')
        if v not in scope_options:
            raise ValueError(f'"{v}" is not a valid scope. Options are: {", ".join(scope_options)}.')
        return v
