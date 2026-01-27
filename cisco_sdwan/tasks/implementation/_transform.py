import argparse
from uuid import uuid4
from copy import deepcopy
from contextlib import suppress
from typing import Union, Optional, NamedTuple, Annotated
from collections.abc import Callable
from pydantic import model_validator, BaseModel, field_validator, ValidationError, Field, ValidationInfo, ConfigDict
import yaml
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import update_ids, update_crypts, ServerInfo, ConfigItem, ExtendedTemplate
from cisco_sdwan.base.models_vmanage import DeviceTemplate, DeviceTemplateAttached, DeviceTemplateValues
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.tasks.utils import (TaskOptions, TagOptions, existing_workdir_type, filename_type, ext_template_type,
                                     regex_type, existing_file_type)
from cisco_sdwan.tasks.common import clean_dir, Task, TaskException, regex_filter
from cisco_sdwan.tasks.models import const, TaskArgs, CatalogTag
from cisco_sdwan.tasks.validators import (validate_workdir, validate_ext_template, validate_filename, validate_regex,
                                          validate_existing_file, validate_json)


class RecipeException(Exception):
    """ Exception indicating issues with the transform recipe """
    pass


class TransformRecipeNameTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regex: Optional[str] = None
    not_regex: Optional[str] = None
    name_regex: str

    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)
    _validate_name_regex = field_validator('name_regex')(validate_ext_template)


RECIPE_VALUE_CHANGE_ME: str = '< CHANGE ME >'


class ValueMap(BaseModel):
    from_value: str
    to_value: str


class CryptResourceUpdate(BaseModel):
    resource_name: str
    replacements: list[ValueMap]


class TransformRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: CatalogTag
    name_template: Optional[TransformRecipeNameTemplate] = None
    name_map: Annotated[Optional[dict[str, str]], Field(validate_default=True)] = None
    crypt_updates:  Optional[list[CryptResourceUpdate]] = None
    replace_source: bool = True

    # Validators
    @field_validator('name_map')
    @classmethod
    def validate_name_map(cls, v, info: ValidationInfo):
        if v is None and info.data.get('name_template') is None and info.data.get('crypt_updates') is not None:
            raise ValueError('At least one of "name_map" or "name_template" needs to be provided')
        return v

    @classmethod
    def parse_yaml(cls, filename: str):
        try:
            with open(filename) as yaml_file:
                recipe_dict = yaml.safe_load(yaml_file)
                return cls.model_validate(recipe_dict)
        except FileNotFoundError as ex:
            raise RecipeException(f'Could not load recipe file: {ex}') from None
        except yaml.YAMLError as ex:
            raise RecipeException(f'Recipe file YAML syntax error: {ex}') from None


class ProcessorMatch(NamedTuple):
    matched: bool
    new_name: Optional[str] = None


class Processor:
    def __init__(self, name: str, recipe: TransformRecipe):
        self.name = name
        self.recipe = recipe

    def match(self, name: str, tag: str) -> ProcessorMatch:
        """
        Checks whether the config item matches this processor, that is, if the item name and tag match any recipe rule.
        In case of a match, a new name may be provided (based on recipe rules):
        - If name_map is defined in the recipe and there is mapping for the current name, then use it.
        - If name_regex is defined in the recipe, then use it to build the new name.

        @param name: The name of the config item to match
        @param tag: Tag associated with the config item to match
        @return: A ProcessorMatch object indicating whether the config item matched and if a new name should be used.
        """
        # Match tag
        if self.recipe.tag != CATALOG_TAG_ALL and self.recipe.tag != tag:
            return ProcessorMatch(False)

        # Match name_map
        if self.recipe.name_map is not None and name in self.recipe.name_map:
            return ProcessorMatch(True, self.recipe.name_map[name])

        # Match regex / name_regex
        if self.recipe.name_template is not None and regex_filter(self.recipe.name_template.regex,
                                                                  self.recipe.name_template.not_regex, name):
            return ProcessorMatch(True, ExtendedTemplate(self.recipe.name_template.name_regex)(name))

        # Match crypt_updates
        if self.recipe.crypt_updates is not None and name in {rsc.resource_name for rsc in self.recipe.crypt_updates}:
            return ProcessorMatch(True)

        return ProcessorMatch(False)

    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> tuple[dict, list[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: list[str] = []

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

        # Process crypt updates
        if self.recipe.crypt_updates:
            for matched_resource in (rsc for rsc in self.recipe.crypt_updates if rsc.resource_name == new_name):
                trace_log.append(f'Applying crypt updates')
                replacements_map = {entry.from_value: entry.to_value for entry in matched_resource.replacements}
                new_payload = update_crypts(replacements_map, new_payload)

        return new_payload, trace_log

    @property
    def replace_source(self):
        return self.recipe.replace_source


class AttachedProcessor(Processor):
    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> tuple[dict, list[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: list[str] = []

        return new_payload, trace_log


class ValuesProcessor(Processor):
    def eval(self, config_obj: ConfigItem, new_name: str, new_id: str) -> tuple[dict, list[str]]:
        new_payload = deepcopy(config_obj.data)
        trace_log: list[str] = []

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
        rename_parser.set_defaults(subtask_handler=TaskTransform.transform,
                                   recipe_handler=TaskTransform.rename_recipe)

        copy_parser = sub_tasks.add_parser('copy', help='copy configuration items')
        copy_parser.set_defaults(subtask_handler=TaskTransform.transform,
                                 recipe_handler=TaskTransform.copy_recipe)

        recipe_parser = sub_tasks.add_parser('recipe', help='transform using custom recipe')
        recipe_parser.set_defaults(subtask_handler=TaskTransform.transform,
                                   recipe_handler=TaskTransform.load_recipe)
        recipe_mutex = recipe_parser.add_mutually_exclusive_group(required=True)
        recipe_mutex.add_argument('--from-file', metavar='<filename>', type=existing_file_type,
                                  help='load recipe from YAML file')
        recipe_mutex.add_argument('--from-json', metavar='<json>',
                                  help='load recipe from JSON-formatted string')

        build_parser = sub_tasks.add_parser('build-recipe',
                                            help='generate recipe file for updating vManage-encrypted fields')
        build_parser.set_defaults(subtask_handler=TaskTransform.build_recipe)
        build_parser.add_argument('recipe_file', metavar='<filename>', type=filename_type,
                                  help='name for generated recipe file')

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

        for sub_task in (rename_parser, copy_parser, recipe_parser, build_parser):
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
            return TransformRecipe.model_validate_json(parsed_args.from_json)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        if parsed_args.workdir is not None:
            source_info = f'Local workdir: "{parsed_args.workdir}"'
        else:
            source_info = f'vManage URL: "{api.base_url}"'

        if hasattr(parsed_args, 'output'):
            self.log_info(f'Transform task: {source_info} -> Local output dir: "{parsed_args.output}"')
        else:
            self.log_info(f'Transform build-recipe task: {source_info} -> Recipe file: "{parsed_args.recipe_file}"')

        if api is None:
            backend = parsed_args.workdir
            local_info = ServerInfo.load(backend)
            server_version = local_info.server_version if local_info is not None else None
        else:
            backend = api
            server_version = backend.server_version

        return parsed_args.subtask_handler(self, parsed_args, backend, server_version)

    def transform(self, parsed_args, backend: Union[Rest, str], server_version: Optional[str]) -> Union[None, list]:
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

        # The output directory must be empty for a new transform
        saved_output = clean_dir(parsed_args.output, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_output:
            self.log_info(f'Previous output under "{parsed_args.output}" was saved as "{saved_output}"')

        if server_version is not None:
            if ServerInfo(server_version=server_version).save(parsed_args.output):
                self.log_info('Saved vManage server information')

        # Process items
        id_mapping: dict[str, str] = {}  # {<old_id>: <new_id>}
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
                            match_result = processor.match(item_name, tag)
                            if not match_result.matched:
                                raise StopProcessorException()

                            self.log_info(f'Matched {info} {item_name}')
                            if match_result.new_name is not None:
                                new_name = match_result.new_name

                                if not item_cls.is_name_valid(new_name):
                                    self.log_error(f'New {info} name is not valid: {new_name}')
                                    is_bad_name = True
                                    raise StopProcessorException()

                                if new_name in name_set:
                                    self.log_error(f'New {info} name already exists: {new_name}')
                                    is_bad_name = True
                                    raise StopProcessorException()

                            else:
                                new_name = item_name

                            new_id = item_id if processor.replace_source or match_result.new_name is None else str(uuid4())
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

                            # When the item name is unchanged, always replace the source
                            if processor.replace_source or match_result.new_name is None:
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

    def build_recipe(self, parsed_args, backend: Union[Rest, str], server_version: Optional[str]) -> Union[None, list]:
        try:
            tag_set = set()
            resources = []
            for tag in ordered_tags(CATALOG_TAG_ALL, reverse=True):
                self.log_info(f'Inspecting {tag} items')
                for _, info, index_cls, item_cls in catalog_iter(tag, version=server_version):
                    item_index = self.index_get(index_cls, backend)
                    if item_index is None:
                        self.log_debug(f'Skipped {info}, none found')
                        continue

                    for item_id, item_name in item_index:
                        item = self.retrieve(item_cls, backend, item_id, item_name, item_index.need_extended_name)
                        if item is None:
                            self.log_error(f'Failed loading {info} {item_name}')
                            continue
                        self.log_debug(f'Evaluating {info} {item_name}')

                        crypt_values_set = set(item.crypt_cluster_values)

                        if isinstance(item, DeviceTemplate):
                            if item.devices_attached is not None:
                                crypt_values_set.update(item.devices_attached.crypt_cluster_values)

                            if item.attach_values is not None:
                                crypt_values_set.update(item.attach_values.crypt_cluster_values)

                        if crypt_values_set:
                            self.log_info(f'Found {len(crypt_values_set)} crypt value{"s"[:len(crypt_values_set) ^ 1]} '
                                          f'in {info} {item_name}')
                            replacements = [
                                ValueMap(from_value=value, to_value=RECIPE_VALUE_CHANGE_ME) for value in crypt_values_set
                            ]
                            resources.append(CryptResourceUpdate(resource_name=item_name, replacements=replacements))
                            tag_set.add(tag)

            if resources:
                update_recipe = TransformRecipe(tag=next(iter(tag_set)) if len(tag_set) == 1 else CATALOG_TAG_ALL,
                                                crypt_updates=resources)
                with open(parsed_args.recipe_file, 'w') as file:
                    yaml.dump(update_recipe.model_dump(exclude_none=True, exclude_defaults=True),
                              sort_keys=False, indent=2, stream=file)
                self.log_info(f'Recipe file saved as "{parsed_args.recipe_file}"')
            else:
                self.log_warning(f'No encrypted passwords found!')

        except ProcessorException as ex:
            raise TaskException(f'Transform build-recipe aborted: {ex}') from None

        return

    def retrieve(self, item_cls: type[ConfigItem], backend: Union[Rest, str],
                 item_id: str, item_name: str, ext_name: bool) -> Union[ConfigItem, None]:

        item = self.item_get(item_cls, backend, item_id, item_name, ext_name)
        if item is None:
            return None

        if isinstance(item, DeviceTemplate):
            is_api = isinstance(backend, Rest)
            if is_api:
                devices_attached = DeviceTemplateAttached.get_raise(backend, item_id)
            else:
                # devices_attached will be None if there are no attachments (i.e., the file is not present)
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
    subtask_handler: const(Callable, TaskTransform.transform)
    output: str
    workdir: Optional[str] = None
    no_rollover: bool = False

    # Validators
    _validate_filename = field_validator('output')(validate_filename)
    _validate_workdir = field_validator('workdir')(validate_workdir)


class TransformCopyArgs(TransformArgs):
    recipe_handler: const(Callable, TaskTransform.copy_recipe)
    tag: CatalogTag
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    name_regex: str

    # Validators
    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)
    _validate_name = field_validator('name_regex')(validate_ext_template)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'TransformCopyArgs':
        if self.regex is not None and self.not_regex is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return self


class TransformRenameArgs(TransformCopyArgs):
    recipe_handler: const(Callable, TaskTransform.rename_recipe)


class TransformRecipeArgs(TransformArgs):
    recipe_handler: const(Callable, TaskTransform.load_recipe)
    from_file: Optional[str] = None
    from_json: Optional[str] = None

    # Validators
    _validate_existing_file = field_validator('from_file')(validate_existing_file)
    _validate_json = field_validator('from_json')(validate_json)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'TransformRecipeArgs':
        if self.from_file is not None and self.from_json is not None:
            raise ValueError('Argument "from_file" not allowed with "from_json"')

        return self


class TransformBuildRecipeArgs(TaskArgs):
    subtask_handler: const(Callable, TaskTransform.build_recipe)
    workdir: Optional[str] = None
    recipe_file: str

    # Validators
    _validate_filename = field_validator('recipe_file')(validate_filename)
    _validate_workdir = field_validator('workdir')(validate_workdir)
