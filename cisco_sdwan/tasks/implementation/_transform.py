import argparse
from uuid import uuid4
from copy import deepcopy
from contextlib import suppress
from typing import Union, Optional, Tuple, List, Dict, Type, Callable, Any
from pydantic import BaseModel, validator, ValidationError, Extra, root_validator
import yaml
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import update_ids, ServerInfo, ConfigItem, ExtendedTemplate
from cisco_sdwan.base.models_vmanage import DeviceTemplate, DeviceTemplateAttached, DeviceTemplateValues
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.tasks.utils import (TaskOptions, TagOptions, existing_workdir_type, filename_type, ext_template_type,
                                     regex_type, existing_file_type)
from cisco_sdwan.tasks.common import clean_dir, Task, TaskException, regex_search
from cisco_sdwan.tasks.models import const, TaskArgs, validate_catalog_tag
from cisco_sdwan.tasks.validators import (validate_workdir, validate_ext_template, validate_filename, validate_regex,
                                          validate_existing_file, validate_json)


class RecipeException(Exception):
    """ Exception indicating issues with the transform recipe """
    pass


class TransformRecipeNameTemplate(BaseModel, extra=Extra.forbid):
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    name_regex: str

    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_name_regex = validator('name_regex', allow_reuse=True)(validate_ext_template)


class TransformRecipe(BaseModel, extra=Extra.forbid):
    tag: str
    name_template: Optional[TransformRecipeNameTemplate] = None
    name_map: Optional[Dict[str, str]] = None
    replace_source: bool = True

    # Validators
    _validate_tag = validator('tag', allow_reuse=True)(validate_catalog_tag)

    @validator('name_map',  always=True)
    def validate_name_map(cls, v, values):
        if v is None and values.get('name_template') is None:
            raise ValueError('At least one of "name_map" or "name_template" needs to be provided')
        return v

    def __init__(self, **kwargs):
        # Dummy init used so PyCharm type checker can recognize parameters
        super().__init__(**kwargs)

    @classmethod
    def parse_yaml(cls, filename: str):
        try:
            with open(filename) as yaml_file:
                recipe_dict = yaml.safe_load(yaml_file)
                return cls.parse_obj(recipe_dict)
        except FileNotFoundError as ex:
            raise RecipeException(f'Could not load recipe file: {ex}') from None
        except yaml.YAMLError as ex:
            raise RecipeException(f'Recipe file YAML syntax error: {ex}') from None


class Processor:
    def __init__(self, name: str, recipe: TransformRecipe):
        self.name = name
        self.recipe = recipe

    def match(self, name: str, tag: str) -> Union[str, None]:
        """
        Create a new name. If name_map is defined in the recipe and there is mapping for the current name, then use it.
        Otherwise, if name_regex is defined in the recipe, then use it to build the new name.
        """
        # Match tag
        if self.recipe.tag != CATALOG_TAG_ALL and self.recipe.tag != tag:
            return None

        # Match name_map
        new_name = self.recipe.name_map.get(name) if self.recipe.name_map is not None else None

        # Match regex / name_regex
        if new_name is None and self.recipe.name_template is not None:
            regex = self.recipe.name_template.regex or self.recipe.name_template.not_regex
            if regex is None or regex_search(regex, name, inverse=self.recipe.name_template.regex is None):
                new_name = ExtendedTemplate(self.recipe.name_template.name_regex)(name)

        return new_name

    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> Tuple[dict, List[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: List[str] = []

        if config_obj.name_tag:
            new_payload[config_obj.name_tag] = new_name
        # In older releases, device templates did not have a templateId
        if config_obj.id_tag and config_obj.id_tag in new_payload:
            new_payload[config_obj.id_tag] = new_id

        # Reset attributes that would make this item read-Only
        for ro_tag in (config_obj.factory_default_tag, config_obj.readonly_tag):
            if new_payload.get(ro_tag, False):
                new_payload[ro_tag] = False
                trace_log.append(f'Resetting "{ro_tag}" flag to "False"')

        return new_payload, trace_log

    @property
    def replace_source(self):
        return self.recipe.replace_source


class AttachedProcessor(Processor):
    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> Tuple[dict, List[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: List[str] = []

        return new_payload, trace_log


class ValuesProcessor(Processor):
    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> Tuple[dict, List[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: List[str] = []

        return new_payload, trace_log


@TaskOptions.register('transform')
class TaskTransform(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nTransform task:')
        task_parser.prog = f'{task_parser.prog} transform'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='transform options')
        sub_tasks.required = True

        rename_parser = sub_tasks.add_parser('rename', help='rename configuration items')
        rename_parser.set_defaults(recipe_handler=TaskTransform.rename_recipe)

        copy_parser = sub_tasks.add_parser('copy', help='copy configuration items')
        copy_parser.set_defaults(recipe_handler=TaskTransform.copy_recipe)

        recipe_parser = sub_tasks.add_parser('recipe', help='transform using custom recipe')
        recipe_parser.set_defaults(recipe_handler=TaskTransform.load_recipe)
        recipe_mutex = recipe_parser.add_mutually_exclusive_group(required=True)
        recipe_mutex.add_argument('--from-file', metavar='<filename>', type=existing_file_type,
                                  help='load recipe from YAML file')
        recipe_mutex.add_argument('--from-json', metavar='<json>',
                                  help='load recipe from JSON-formatted string')

        for sub_task in (rename_parser, copy_parser):
            sub_task.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                  help='tag for selecting items to transform. Available tags: '
                                       f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
            mutex = sub_task.add_mutually_exclusive_group()
            mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='regular expression selecting item names to transform')
            mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                               help='regular expression selecting item names NOT to transform')
            sub_task.add_argument('name_regex', metavar='<name-regex>', type=ext_template_type,
                                  help='name-regex used to transform an existing item name. Variable {name} is '
                                       'replaced with the original template name. Sections of the original template '
                                       'name can be selected using the {name <regex>} format. Where <regex> is a '
                                       'regular expression that must contain at least one capturing group. Capturing '
                                       'groups identify sections of the original name to keep.')

        for sub_task in (rename_parser, copy_parser, recipe_parser):
            sub_task.add_argument('output', metavar='<output-directory>', type=filename_type,
                                  help='directory to save transform result')
            sub_task.add_argument('--no-rollover', action='store_true',
                                  help='by default, if the output directory already exists it is renamed using a '
                                       'rolling naming scheme. This option disables this automatic rollover.')
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                  help='transform will read from the specified directory instead of target vManage')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args) -> bool:
        return parsed_args.workdir is None

    @staticmethod
    def _recipe_dict(parsed_args, replace_source: bool) -> dict:
        recipe_dict = {
            'tag': parsed_args.tag,
            'name_template': {
                'name_regex': parsed_args.name_regex
            },
            'replace_source': replace_source
        }
        if parsed_args.regex:
            recipe_dict['name_template']['regex'] = parsed_args.regex
        elif parsed_args.not_regex:
            recipe_dict['name_template']['not_regex'] = parsed_args.not_regex

        return recipe_dict

    @classmethod
    def rename_recipe(cls, parsed_args) -> TransformRecipe:
        return TransformRecipe(**cls._recipe_dict(parsed_args, replace_source=True))

    @classmethod
    def copy_recipe(cls, parsed_args) -> TransformRecipe:
        return TransformRecipe(**cls._recipe_dict(parsed_args, replace_source=False))

    @staticmethod
    def load_recipe(parsed_args) -> TransformRecipe:
        if parsed_args.from_file:
            return TransformRecipe.parse_yaml(parsed_args.from_file)
        else:
            return TransformRecipe.parse_raw(parsed_args.from_json)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info(f'Transform task: {source_info} -> Local output dir: "{parsed_args.output}"')

        # Load processors
        try:
            recipe = parsed_args.recipe_handler(parsed_args)
            default_processor = Processor(name='default', recipe=recipe)
            loaded_processors = {
                DeviceTemplateAttached: AttachedProcessor(name='attached devices processor', recipe=recipe),
                DeviceTemplateValues: ValuesProcessor(name='values processor', recipe=recipe)
            }
        except (ValidationError, RecipeException) as ex:
            raise TaskException(f'Error loading transform recipe: {ex}') from None

        # Output directory must be empty for a new transform
        saved_output = clean_dir(parsed_args.output, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_output:
            self.log_info(f'Previous output under "{parsed_args.output}" was saved as "{saved_output}"')

        # Identify backend and server version
        if api is None:
            backend = parsed_args.workdir
            local_info = ServerInfo.load(backend)
            server_version = local_info.server_version if local_info is not None else None
        else:
            backend = api
            server_version = backend.server_version

        if server_version is not None:
            if ServerInfo(server_version=server_version).save(parsed_args.output):
                self.log_info('Saved vManage server information')

        # Process items
        id_mapping: Dict[str, str] = {}  # {<old_id>: <new_id>}
        try:
            for tag in ordered_tags(CATALOG_TAG_ALL, reverse=True):
                self.log_info(f'Inspecting {tag} items')

                for _, info, index_cls, item_cls in catalog_iter(tag, version=server_version):
                    item_index = self.index_get(index_cls, backend)
                    if item_index is None:
                        self.log_debug(f'Skipped {info}, none found')
                        continue

                    processor = loaded_processors.get(item_cls, default_processor)
                    name_set = {item_name for item_id, item_name in item_index}
                    is_bad_name = False
                    export_list = []
                    id_hint_map = {item_name: item_id for item_id, item_name in item_index}

                    for item_id, item_name in item_index:
                        item = self.retrieve(item_cls, backend, item_id, item_name, item_index.need_extended_name)
                        if item is None:
                            self.log_error(f'Failed loading {info} {item_name}')
                            continue

                        self.log_debug(f'Evaluating {info} {item_name} with {processor.name} processor')
                        with suppress(StopProcessorException):
                            new_name = processor.match(item_name, tag)
                            if new_name is None:
                                raise StopProcessorException()

                            self.log_info(f'Matched {info} {item_name}')
                            if not item_cls.is_name_valid(new_name):
                                self.log_error(f'New {info} name is not valid: {new_name}')
                                is_bad_name = True
                                raise StopProcessorException()
                            if new_name in name_set:
                                self.log_error(f'New {info} name already exists: {new_name}')
                                is_bad_name = True
                                raise StopProcessorException()

                            new_id = item_id if processor.replace_source else str(uuid4())
                            new_payload = self.processor_eval(processor, item, new_name, new_id)
                            new_item = item_cls(update_ids(id_mapping, new_payload))

                            if isinstance(item, DeviceTemplate):
                                if item.devices_attached is not None:
                                    b_processor = loaded_processors.get(DeviceTemplateAttached, default_processor)
                                    new_item.devices_attached = DeviceTemplateAttached(
                                        self.processor_eval(b_processor, item.devices_attached, new_name, new_id)
                                    )
                                if item.attach_values is not None:
                                    b_processor = loaded_processors.get(DeviceTemplateValues, default_processor)
                                    new_item.attach_values = DeviceTemplateValues(
                                        self.processor_eval(b_processor, item.attach_values, new_name, new_id)
                                    )

                            if processor.replace_source:
                                self.log_info(f'Replacing {info}: {item_name} -> {new_name}')
                                item = new_item
                            else:
                                self.log_info(f'Adding {info}: {new_name}')
                                export_list.append(new_item)
                                id_mapping[item_id] = new_id

                            name_set.add(new_name)
                            id_hint_map[new_name] = new_id

                        export_list.append(item)

                    if is_bad_name:
                        raise TaskException(f'One or more {info} new names are invalid')

                    if not export_list:
                        self.log_debug(f'No {info} to export')
                        continue

                    x_item_index = index_cls.create(export_list, id_hint_map)
                    if x_item_index.save(parsed_args.output):
                        self.log_debug(f'Saved {info} index')

                    for x_item in export_list:
                        save_params = (parsed_args.output, x_item_index.need_extended_name, x_item.name,
                                       id_hint_map[x_item.name])
                        if x_item.save(*save_params):
                            self.log_debug(f'Saved {info} {x_item.name}')

                        if isinstance(x_item, DeviceTemplate):
                            if x_item.devices_attached is not None and x_item.devices_attached.save(*save_params):
                                self.log_debug(f'Saved {info} {x_item.name} attached devices')
                            if x_item.attach_values is not None and x_item.attach_values.save(*save_params):
                                self.log_debug(f'Saved {info} {x_item.name} values')

        except ProcessorException as ex:
            raise TaskException(f'Transform aborted: {ex}') from None

        return

    def retrieve(self, item_cls: Type[ConfigItem], backend: Union[Rest, str],
                 item_id: str, item_name: str, ext_name: bool) -> Union[ConfigItem, None]:

        item = self.item_get(item_cls, backend, item_id, item_name, ext_name)
        if item is None:
            return None

        if isinstance(item, DeviceTemplate):
            is_api = isinstance(backend, Rest)
            if is_api:
                devices_attached = DeviceTemplateAttached.get_raise(backend, item_id)
            else:
                # devices_attached will be None if there are no attachments (i.e. file is not present)
                devices_attached = DeviceTemplateAttached.load(backend, ext_name, item_name, item_id)

            if devices_attached is not None and not devices_attached.is_empty:
                if is_api:
                    uuid_iter = (uuid for uuid, _ in devices_attached)
                    attach_values = DeviceTemplateValues.get_values(backend, item_id, uuid_iter)
                else:
                    attach_values = DeviceTemplateValues.load(backend, ext_name, item_name, item_id)

                if attach_values is None:
                    self.log_error(f'Failed loading {item_name} values')
                else:
                    item.devices_attached = devices_attached
                    item.attach_values = attach_values

        return item

    def processor_eval(self, p: Processor, config_obj: ConfigItem, new_name: str, new_id: str) -> dict:
        new_payload, trace_log = p.eval(config_obj, new_name, new_id)
        for trace in trace_log:
            self.log_debug(f'Processor {p.name}, {new_name}: {trace}')

        return new_payload


class TransformArgs(TaskArgs):
    output: str
    workdir: Optional[str] = None
    no_rollover: bool = False

    # Validators
    _validate_filename = validator('output', allow_reuse=True)(validate_filename)
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)


class TransformCopyArgs(TransformArgs):
    recipe_handler: Callable = const(TaskTransform.copy_recipe)
    tag: str
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    name_regex: str

    # Validators
    _validate_tag = validator('tag', allow_reuse=True)(validate_catalog_tag)
    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_name = validator('name_regex', allow_reuse=True)(validate_ext_template)

    @root_validator(skip_on_failure=True)
    def mutex_validations(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('regex') is not None and values.get('not_regex') is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return values


class TransformRenameArgs(TransformCopyArgs):
    recipe_handler: Callable = const(TaskTransform.rename_recipe)


class TransformRecipeArgs(TransformArgs):
    recipe_handler: Callable = const(TaskTransform.load_recipe)
    from_file: Optional[str] = None
    from_json: Optional[str] = None

    # Validators
    _validate_existing_file = validator('from_file', allow_reuse=True)(validate_existing_file)
    _validate_json = validator('from_json', allow_reuse=True)(validate_json)

    @root_validator(skip_on_failure=True)
    def mutex_validations(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get('from_file') is not None and values.get('from_json') is not None:
            raise ValueError('Argument "from_file" not allowed with "from_json"')

        return values
