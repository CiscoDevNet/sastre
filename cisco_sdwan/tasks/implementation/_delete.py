import argparse
from typing import Union, Optional
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from pydantic import model_validator, field_validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.models_base import FeatureProfile, ModelException
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags, is_index_supported
from cisco_sdwan.base.models_vmanage import DeviceTemplateIndex, ConfigGroupIndex, ProfileSdwanPolicy, Tag
from cisco_sdwan.tasks.utils import TaskOptions, TagOptions, regex_type
from cisco_sdwan.tasks.common import regex_filter, Task, WaitActionsException
from cisco_sdwan.tasks.models import TaskArgs, CatalogTag
from cisco_sdwan.tasks.validators import validate_regex


@TaskOptions.register('delete')
class TaskDelete(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nDelete task:')
        task_parser.prog = f'{task_parser.prog} delete'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        mutex = task_parser.add_mutually_exclusive_group()
        mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names to delete, within selected tags.')
        mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names NOT to delete, within selected tags.')
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='dry-run mode. Items matched for removal are listed but not deleted.')
        task_parser.add_argument('--detach', action='store_true',
                                 help='USE WITH CAUTION! Detach templates, dissociate config-groups and deactivate '
                                      'vSmart policy before deleting items. This allows deleting items '
                                      'that are associated with attachments, deployments and active policies.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='tag for selecting items to be deleted. Available tags: '
                                      f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.is_dryrun = parsed_args.dryrun
        self.log_info(f'Delete task: vManage URL: "{api.base_url}"')

        regex_filter_fn = partial(regex_filter, parsed_args.regex, parsed_args.not_regex)

        if parsed_args.detach:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)

                # Detach WAN Edge templates
                reqs = self.template_detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart,
                                                                              DeviceTemplateIndex.is_attached),
                                            log_context='template detaching WAN Edges')
                if reqs:
                    self.log_debug(f'Detach requests processed: {reqs}')
                else:
                    self.log_info('No WAN Edge template detachments needed')

                # Deactivate vSmart policy
                reqs = self.policy_deactivate(api, log_context='deactivating vSmart policy')
                if reqs:
                    self.log_debug(f'Deactivate requests processed: {reqs}')
                else:
                    self.log_info('No vSmart policy deactivate needed')

                # Detach vSmart templates
                reqs = self.template_detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_vsmart,
                                                                              DeviceTemplateIndex.is_attached),
                                            log_context='template detaching vSmarts')
                if reqs:
                    self.log_debug(f'Detach requests processed: {reqs}')
                else:
                    self.log_info('No vSmart template detachments needed')

                # Dissociate WAN Edge config-groups
                if is_index_supported(ConfigGroupIndex, version=api.server_version):
                    config_groups = ConfigGroupIndex.get_raise(api)

                    diss_reqs = self.cfg_group_dissociate(api, config_groups,
                                                          log_context='config-group dissociating WAN Edges')
                    if diss_reqs:
                        self.log_debug(f'Dissociate requests processed: {diss_reqs}')

                    rule_reqs = self.cfg_group_rules_delete(api, config_groups)
                    if rule_reqs:
                        self.log_debug(f'Automated rule delete requests processed: {rule_reqs}')

                    if not (diss_reqs + rule_reqs):
                        self.log_info('No WAN Edge config-group dissociate or automated rule deletes needed')

            except (RestAPIException, WaitActionsException) as ex:
                self.log_critical(f'Detach failed: {ex}')
                return

        for tag in ordered_tags(parsed_args.tag, parsed_args.tag != CATALOG_TAG_ALL):
            self.log_info(f'Inspecting {tag} items', dryrun=False)
            matched_item_iter = (
                (item_name, item_id, item_cls, info)
                for _, info, index, item_cls in self.index_iter(api, catalog_iter(tag, version=api.server_version))
                for item_id, item_name in index
                if regex_filter_fn(item_name) or issubclass(item_cls, ProfileSdwanPolicy)
            )
            for item_name, item_id, item_cls, info in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    self.log_warning(f'Failed retrieving {info} {item_name}')
                    continue

                if isinstance(item, ProfileSdwanPolicy):
                    # Special case for policy objects, which cannot be deleted, allowing deletion of its parcels only
                    self.delete_linked_parcels(api, item, item_id, info, regex_filter_fn)
                    continue

                if item.is_readonly or item.is_system:
                    self.log_debug(f'Skipped {"read-only" if item.is_readonly else "system"} {info} {item_name}')
                    continue

                if self.is_dryrun:
                    self.log_info(f'Delete {info} {item_name}')
                    continue

                try:
                    if isinstance(item, Tag):
                        # Special case for deleting tags, item id is passed as url parameter instead of in the path
                        api.delete(item_cls.api_path.delete, **Tag.delete_params(item_id))
                    else:
                        api.delete(item_cls.api_path.delete, item_id)
                except RestAPIException as ex:
                    self.log_warning(f'Failed: Delete {info} {item_name}: {ex}')
                else:
                    self.log_info(f'Done: Delete {info} {item_name}')

        return

    def delete_linked_parcels(self, api: Rest, target_profile: FeatureProfile, profile_id: str,
                              info: str, filter_fn: Callable[[str], bool]) -> None:
        parcel_coro = target_profile.associated_parcels(profile_id, target_profile=target_profile, delete_order=True)

        with suppress(StopIteration):
            parcel_id = None
            while True:
                try:
                    if parcel_id is None:
                        parcel_info = next(parcel_coro)
                    else:
                        parcel_info = parcel_coro.send(parcel_id)

                    parcel_id = parcel_info.target_id

                    if not filter_fn(parcel_info.name):
                        # Parcel did not match the filter
                        continue

                    if parcel_info.is_system:
                        self.log_debug(f'Skipped system {info} {target_profile.name} parcel {parcel_info.name}')
                        continue

                    if self.is_dryrun:
                        self.log_info(f'Delete {info} {target_profile.name} parcel {parcel_info.name}')
                        continue

                    api.delete(parcel_info.api_path.delete, parcel_info.target_id)
                    self.log_info(f'Done: Delete {info} {target_profile.name} parcel {parcel_info.name}')
                except (ModelException, RestAPIException) as ex:
                    self.log_error(f'Failed: Delete {info} {target_profile.name} parcel: {ex}')


class DeleteArgs(TaskArgs):
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    dryrun: bool = False
    detach: bool = False
    tag: CatalogTag

    # Validators
    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'DeleteArgs':
        if self.regex is not None and self.not_regex is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return self
