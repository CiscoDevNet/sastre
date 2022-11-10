import argparse
from typing import Union, Optional, Sequence, Dict, Set, Any
from pydantic import validator, root_validator
from uuid import uuid4
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException, is_version_newer, response_id
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags, is_index_supported
from cisco_sdwan.base.models_base import UpdateEval, ServerInfo, ModelException
from cisco_sdwan.base.models_vmanage import (DeviceTemplateIndex, PolicyVsmartIndex, EdgeInventory, ControlInventory,
                                             CheckVBond, FeatureProfile, ConfigGroupIndex)
from cisco_sdwan.tasks.utils import (TaskOptions, TagOptions, regex_type, default_workdir, existing_workdir_type,
                                     TrackedValidator, ConditionalValidator, zip_file_type)
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException, clean_dir, archive_extract
from cisco_sdwan.tasks.models import TaskArgs, validate_catalog_tag, validate_workdir_conditional
from cisco_sdwan.tasks.validators import validate_regex, validate_zip_file


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nRestore task:')
        task_parser.prog = f'{task_parser.prog} restore'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        # Workdir validation is done only if archive validation has not, that is if this is a restore from directory
        tracked_archive_type = TrackedValidator(zip_file_type)
        workdir_conditional_type = ConditionalValidator(existing_workdir_type, tracked_archive_type)

        mutex_source = task_parser.add_mutually_exclusive_group()
        mutex_source.add_argument('--archive', metavar='<filename>', type=tracked_archive_type,
                                  help='restore from zip archive')
        mutex_source.add_argument('--workdir', metavar='<directory>', type=workdir_conditional_type,
                                  default=default_workdir(target_address),
                                  help='restore from directory (default: %(default)s)')
        mutex_regex = task_parser.add_mutually_exclusive_group()
        mutex_regex.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='regular expression matching item names to restore, within selected tags.')
        mutex_regex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                                 help='regular expression matching item names NOT to restore, within selected tags.')
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='dry-run mode. Items to be restored are listed but not pushed to vManage.')
        task_parser.add_argument('--attach', action='store_true',
                                 help='attach templates, deploy config-groups and activate vSmart policy after '
                                      'restoring items.')
        task_parser.add_argument('--update', action='store_true',
                                 help='update vManage items that have the same name but different content as the '
                                      'corresponding item in workdir. Without this option, such items are skipped '
                                      'from restore.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='tag for selecting items to be restored. Items that are dependencies of the '
                                      'specified tag are automatically included. Available tags: '
                                      f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        def load_items(index, item_cls):
            item_iter = (
                (item_id, item_cls.load(parsed_args.workdir, index.need_extended_name, item_name, item_id))
                for item_id, item_name in index
            )
            return ((item_id, item_obj) for item_id, item_obj in item_iter if item_obj is not None)

        self.is_dryrun = parsed_args.dryrun

        if parsed_args.archive:
            self.log_info(f'Restore task: Local archive file: "{parsed_args.archive}" -> vManage URL: "{api.base_url}"')
            parsed_args.workdir = str(uuid4())
            self.log_debug(f'Temporary workdir: {parsed_args.workdir}')

            archive_extract(parsed_args.archive, parsed_args.workdir)
            self.log_info(f'Loaded archive file "{parsed_args.archive}"')
        else:
            self.log_info(f'Restore task: Local workdir: "{parsed_args.workdir}" -> vManage URL: "{api.base_url}"')

        local_info = ServerInfo.load(parsed_args.workdir)
        # Server info file may not be present (e.g. backup from older Sastre releases)
        if local_info is not None and is_version_newer(api.server_version, local_info.server_version):
            self.log_warning(f'Target vManage release ({api.server_version}) is older than the release used in backup '
                             f'({local_info.server_version}). Items may fail to restore due to incompatibilities.')

        is_vbond_set = self.is_vbond_configured(api)

        self.log_info('Loading existing items from target vManage', dryrun=False)
        target_all_items_map = {
            hash(type(index)): {item_name: item_id for item_id, item_name in index}
            for _, _, index, item_cls in self.index_iter(api, catalog_iter(CATALOG_TAG_ALL, version=api.server_version))
        }

        self.log_info('Identifying items to be pushed', dryrun=False)
        id_mapping = {}  # {<old_id>: <new_id>}, used to replace old (saved) item ids with new (target) ids
        restore_list = []  # [ (<info>, <index_cls>, [(<item_id>, <item>, <id_on_target>), ...]), ...]
        dependency_set = set()  # {<item_id>, ...}
        match_set = set()  # {<item_id>, ...}
        for tag in ordered_tags(parsed_args.tag):
            if tag == 'template_device' and not is_vbond_set:
                self.log_warning(f'Will skip {tag} items because vBond is not configured. '
                                 'On vManage, Administration > Settings > vBond.')
                continue

            self.log_info(f'Inspecting {tag} items', dryrun=False)
            tag_iter = (
                (info, index, load_items(index, item_cls))
                for _, info, index, item_cls in self.index_iter(parsed_args.workdir,
                                                                catalog_iter(tag, version=api.server_version))
            )
            for info, index, loaded_items_iter in tag_iter:
                target_item_map = target_all_items_map.get(hash(type(index)))
                if target_item_map is None:
                    # Logging at warning level because the backup files did have this item
                    self.log_warning(f'Will skip {info}, item not supported by target vManage')
                    continue

                restore_item_list = []
                for item_id, item in loaded_items_iter:
                    target_id = target_item_map.get(item.name)
                    if target_id is not None:
                        # Item already exists on target vManage, record item id from target
                        if item_id != target_id:
                            id_mapping[item_id] = target_id

                        if not parsed_args.update:
                            # Existing item on target vManage will be used, i.e. will not update it
                            self.log_debug(f'Will skip {info} {item.name}, item already on target vManage')
                            continue

                    regex = parsed_args.regex or parsed_args.not_regex
                    item_matches = (
                            not item.is_readonly and
                            (parsed_args.tag == CATALOG_TAG_ALL or parsed_args.tag == tag) and
                            (regex is None or regex_search(regex, item.name, inverse=parsed_args.regex is None))
                    )
                    if item_matches:
                        match_set.add(item_id)
                    if item_matches or item_id in dependency_set:
                        # A target_id that is not None signals a put operation (update), as opposed to post.
                        # target_id will be None unless --update is specified and item name is on target
                        # Read-only items are added only if they are in dependency_set
                        restore_item_list.append((item_id, item, target_id))
                        dependency_set.update(item.id_references_set)

                if len(restore_item_list) > 0:
                    restore_list.append((info, index, restore_item_list))

        if len(restore_list) > 0:
            self.log_info('Pushing items to vManage', dryrun=False)
            self.restore_config_items(api, restore_list, id_mapping, dependency_set, match_set)
        else:
            self.log_info('No items to push')

        if parsed_args.attach:
            for attach_step_fn, info in (('restore_deployments', 'config-group deployments'),
                                         ('restore_attachments', 'template attachments'),
                                         ('restore_active_policy', 'vSmart policy activate')):
                try:
                    getattr(TaskRestore, attach_step_fn)(self, api, parsed_args.workdir)
                except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                    self.log_error(f'Failed: {info}: {ex}')

        if parsed_args.archive:
            clean_dir(parsed_args.workdir, max_saved=0)
            self.log_debug('Temporary workdir deleted')

        return

    def is_vbond_configured(self, api: Rest) -> bool:
        if api.is_multi_tenant and not api.is_provider:
            # Cannot explicitly check vBond configuration with tenant account, assume it is configured
            return True

        check_vbond = CheckVBond.get(api)
        if check_vbond is None:
            self.log_warning('Failed retrieving vBond configuration status.')
            return False

        return check_vbond.is_configured

    def restore_config_items(self, api: Rest, restore_list: Sequence[tuple], id_mapping: Dict[str, str],
                             dependency_set: Set[str], match_set: Set[str]) -> None:
        # Items were added to restore_list following ordered_tags() order (i.e. higher level items before lower
        # level items). The reverse order needs to be followed on restore.
        for info, index, restore_item_list in reversed(restore_list):
            pushed_item_dict = {}
            for item_id, item, target_id in restore_item_list:
                op_info = 'Create' if target_id is None else 'Update'
                reason = ' (dependency)' if item_id in dependency_set - match_set else ''

                try:
                    if target_id is None:
                        # Create new item
                        if item.is_readonly:
                            self.log_warning(f'Factory default {info} {item.name} is a dependency that is missing '
                                             'on target vManage. Will be converted to non-default.')

                        if self.is_dryrun:
                            self.log_info(f'{op_info} {info} {item.name}{reason}')
                            continue
                        # Not using id returned from post because post can return empty (e.g. local policies)
                        response = api.post(item.post_data(id_mapping), item.api_path.post)
                        pushed_item_dict[item.name] = item_id

                        # Special case for FeatureProfiles, creating linked parcels
                        if isinstance(item, FeatureProfile):
                            parcel_coro = item.associated_parcels(response_id(response))
                            try:
                                new_parcel_id = None
                                while True:
                                    try:
                                        if new_parcel_id is None:
                                            api_path, p_info, p_payload = next(parcel_coro)
                                        else:
                                            api_path, p_info, p_payload = parcel_coro.send(new_parcel_id)

                                        new_parcel_id = response_id(api.post(p_payload, api_path.post))
                                    except ModelException as ex:
                                        self.log_error(f'Failed: {op_info} {info} {item.name} parcel{reason}: {ex}')
                                    else:
                                        self.log_info(f'Done: {op_info} {info} {item.name} parcel {p_info}{reason}')
                            except StopIteration:
                                pass

                    else:
                        # Update existing item
                        if item.is_readonly:
                            self.log_debug(f'{op_info} skipped (read-only) {info} {item.name}')
                            continue

                        update_data = item.put_data(id_mapping)
                        if item.get_raise(api, target_id).is_equal(update_data):
                            self.log_debug(f'{op_info} skipped (no diffs) {info} {item.name}')
                            continue

                        if self.is_dryrun:
                            self.log_info(f'{op_info} {info} {item.name}{reason}')
                            continue

                        put_eval = UpdateEval(api.put(update_data, item.api_path.put, target_id))
                        if put_eval.need_reattach:
                            if put_eval.is_master:
                                self.log_info(f'Updating {info} {item.name} requires reattach')
                                attach_data = self.template_reattach_data(api, [(item.name, target_id)])
                            else:
                                self.log_info(
                                    f'Updating {info} {item.name} requires reattach of affected templates'
                                )
                                target_templates = {item_id: item_name
                                                    for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                                templates_iter = (
                                    (target_templates[tgt_id], tgt_id)
                                    for tgt_id in put_eval.templates_affected_iter()
                                )
                                attach_data = self.template_reattach_data(api, templates_iter)

                            # All re-attachments need to be done in a single request, thus 9999 for chunk_size
                            reqs = self.template_attach(api, *attach_data, chunk_size=9999,
                                                        log_context='reattaching templates')
                            self.log_debug(f'Attach requests processed: {reqs}')
                        elif put_eval.need_reactivate:
                            self.log_info(f'Updating {info} {item.name} requires vSmart policy reactivate')
                            self.policy_activate(api, *PolicyVsmartIndex.get_raise(api).active_policy, is_edited=True,
                                                 log_context="reactivating vSmart policy")
                except (RestAPIException, WaitActionsException, ValueError) as ex:
                    self.log_error(f'Failed: {op_info} {info} {item.name}{reason}: {ex}')
                else:
                    self.log_info(f'Done: {op_info} {info} {item.name}{reason}')

            # Read new ids from target and update id_mapping
            try:
                new_target_item_map = {item_name: item_id for item_id, item_name in index.get_raise(api)}
                for item_name, old_item_id in pushed_item_dict.items():
                    id_mapping[old_item_id] = new_target_item_map[item_name]
            except RestAPIException as ex:
                self.log_critical(f'Failed retrieving {info}: {ex}')
                break

    def restore_deployments(self, api: Rest, workdir: str) -> None:
        saved_groups_index = ConfigGroupIndex.load(workdir)
        if saved_groups_index is None:
            self.log_debug("Will skip deployments restore, no local config-group index")
            return

        if not is_index_supported(ConfigGroupIndex, version=api.server_version):
            self.log_debug("Will skip deploy, target vManage does not support config-groups")
            return

        target_groups = {item_name: item_id for item_id, item_name in ConfigGroupIndex.get_raise(api)}
        edges_map = {
            entry.uuid: entry.name
            for entry in EdgeInventory.get_raise(api).filtered_iter(EdgeInventory.is_available, EdgeInventory.is_cedge)
        }
        groups_iter = (
            (saved_name, saved_id, target_groups.get(saved_name)) for saved_id, saved_name in saved_groups_index
        )
        deploy_data = self.cfg_group_deploy_data(
            api, workdir, saved_groups_index.need_extended_name, groups_iter, edges_map
        )
        reqs = self.cfg_group_deploy(api, deploy_data, edges_map, log_context="config-group deploying WAN Edges")
        if reqs:
            self.log_debug(f"Deploy requests processed: {reqs}")
        else:
            self.log_info("No WAN Edge config-group deployments needed")

    def restore_attachments(self, api: Rest, workdir: str) -> None:
        saved_template_index = DeviceTemplateIndex.load(workdir)
        if saved_template_index is None:
            self.log_debug("Will skip attachments restore, no local device template index")
            return

        target_templates = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}

        # Attach WAN Edge templates
        edge_templates_iter = (
            (saved_name, saved_id, target_templates.get(saved_name))
            for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart,
                                                                           DeviceTemplateIndex.is_attached)
        )
        edge_set = {entry.uuid for entry in EdgeInventory.get_raise(api).filtered_iter(EdgeInventory.is_available)}
        attach_data = self.template_attach_data(
            api, workdir, saved_template_index.need_extended_name, edge_templates_iter, target_uuid_set=edge_set
        )
        reqs = self.template_attach(api, *attach_data, log_context="template attaching WAN Edges")
        if reqs:
            self.log_debug(f'Attach requests processed: {reqs}')
        else:
            self.log_info('No WAN Edge template attachments needed')

        # Attach vSmart template
        vsmart_templates_iter = (
            (saved_name, saved_id, target_templates.get(saved_name))
            for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart,
                                                                           DeviceTemplateIndex.is_attached)
        )
        vsmart_set = {
            entry.uuid for entry in ControlInventory.get_raise(api).filtered_iter(ControlInventory.is_available,
                                                                                  ControlInventory.is_vsmart)
        }
        attach_data = self.template_attach_data(
            api, workdir, saved_template_index.need_extended_name, vsmart_templates_iter, target_uuid_set=vsmart_set
        )
        reqs = self.template_attach(api, *attach_data, log_context="template attaching vSmarts")
        if reqs:
            self.log_debug(f'Attach requests processed: {reqs}')
        else:
            self.log_info('No vSmart template attachments needed')

    def restore_active_policy(self, api: Rest, workdir: str) -> None:
        try:
            _, policy_name = PolicyVsmartIndex.load(workdir, raise_not_found=True).active_policy
            target_policies = {item_name: item_id for item_id, item_name in PolicyVsmartIndex.get_raise(api)}
            reqs = self.policy_activate(api, target_policies.get(policy_name), policy_name,
                                        log_context="activating vSmart policy")
            if reqs:
                self.log_debug(f'Activate requests processed: {reqs}')
            else:
                self.log_info('No vSmart policy activate needed')
        except FileNotFoundError:
            self.log_debug("Will skip active policy restore, no local vSmart policy index")


class RestoreArgs(TaskArgs):
    archive: Optional[str] = None
    workdir: Optional[str] = None
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    dryrun: bool = False
    attach: bool = False
    update: bool = False
    tag: str

    # Validators
    _validate_archive = validator('archive', allow_reuse=True)(validate_zip_file)
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir_conditional)
    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_tag = validator('tag', allow_reuse=True)(validate_catalog_tag)

    @root_validator(skip_on_failure=True)
    def mutex_validations(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if bool(values.get('archive')) == bool(values.get('workdir')):
            raise ValueError('Either "archive" or "workdir" must to be provided')

        if values.get('regex') is not None and values.get('not_regex') is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return values
