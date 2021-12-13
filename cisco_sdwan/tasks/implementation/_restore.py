import argparse
from typing import Union, Optional
from pydantic import validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException, is_version_newer
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import UpdateEval, ServerInfo
from cisco_sdwan.base.models_vmanage import (DeviceTemplateIndex, PolicyVsmartIndex, EdgeInventory, ControlInventory,
                                             CheckVBond)
from cisco_sdwan.tasks.utils import TaskOptions, TagOptions, existing_workdir_type, regex_type, default_workdir
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException
from cisco_sdwan.tasks.models import TaskArgs, validate_workdir, validate_regex, validate_catalog_tag


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nRestore task:')
        task_parser.prog = f'{task_parser.prog} restore'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                 default=default_workdir(target_address),
                                 help='restore source (default: %(default)s)')
        mutex = task_parser.add_mutually_exclusive_group()
        mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names to restore, within selected tags.')
        mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names NOT to restore, within selected tags.')
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='dry-run mode. Items to be restored are listed but not pushed to vManage.')
        task_parser.add_argument('--attach', action='store_true',
                                 help='attach devices to templates and activate vSmart policy after restoring items')
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

                    if item.is_readonly:
                        self.log_debug(f'Will skip read-only {info} {item.name}')
                        continue

                    regex = parsed_args.regex or parsed_args.not_regex
                    item_matches = (
                            (parsed_args.tag == CATALOG_TAG_ALL or parsed_args.tag == tag) and
                            (regex is None or regex_search(regex, item.name, inverse=parsed_args.regex is None))
                    )
                    if item_matches:
                        match_set.add(item_id)
                    if item_matches or item_id in dependency_set:
                        # A target_id that is not None signals a put operation, as opposed to post.
                        # target_id will be None unless --update is specified and item name is on target
                        restore_item_list.append((item_id, item, target_id))
                        dependency_set.update(item.id_references_set)

                if len(restore_item_list) > 0:
                    restore_list.append((info, index, restore_item_list))

        if len(restore_list) > 0:
            self.log_info('Pushing items to vManage', dryrun=False)
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
                            if self.is_dryrun:
                                self.log_info(f'{op_info} {info} {item.name}{reason}')
                                continue
                            # Not using item id returned from post because post can return empty (e.g. local policies)
                            api.post(item.post_data(id_mapping), item.api_path.post)
                            pushed_item_dict[item.name] = item_id
                        else:
                            # Update existing item
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
                                    attach_data = self.reattach_template_data(api, [(item.name, target_id)])
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
                                    attach_data = self.reattach_template_data(api, templates_iter)

                                # All re-attachments need to be done in a single request, thus 9999 for chunk_size
                                reqs = self.attach(api, *attach_data, chunk_size=9999,
                                                   log_context='reattaching templates')
                                self.log_debug(f'Attach requests processed: {reqs}')
                            elif put_eval.need_reactivate:
                                self.log_info(f'Updating {info} {item.name} requires vSmart policy reactivate')
                                action_list = self.activate_policy(
                                    api, *PolicyVsmartIndex.get_raise(api).active_policy, is_edited=True
                                )
                                self.wait_actions(api, action_list, 'reactivating vSmart policy', raise_on_failure=True)
                    except (RestAPIException, WaitActionsException) as ex:
                        self.log_error(f'Failed {op_info} {info} {item.name}{reason}: {ex}')
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
        else:
            self.log_info('No items to push')

        if parsed_args.attach:
            try:
                target_templates = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                target_policies = {item_name: item_id for item_id, item_name in PolicyVsmartIndex.get_raise(api)}
                saved_template_index = DeviceTemplateIndex.load(parsed_args.workdir, raise_not_found=True)

                # Attach WAN Edge templates
                edge_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart)
                )
                attach_data = self.attach_template_data(
                    api, parsed_args.workdir, saved_template_index.need_extended_name, edge_templates_iter,
                    target_uuid_set={uuid for uuid, _ in EdgeInventory.get_raise(api)}
                )
                reqs = self.attach(api, *attach_data, log_context='attaching WAN Edges')
                if reqs:
                    self.log_debug(f'Attach requests processed: {reqs}')
                else:
                    self.log_info('No WAN Edge attachments needed')

                # Attach vSmart template
                vsmart_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart)
                )
                vsmart_set = {
                    uuid for uuid, _ in ControlInventory.get_raise(api).filtered_iter(ControlInventory.is_vsmart)
                }
                attach_data = self.attach_template_data(api, parsed_args.workdir,
                                                        saved_template_index.need_extended_name, vsmart_templates_iter,
                                                        target_uuid_set=vsmart_set)
                reqs = self.attach(api, *attach_data, log_context="attaching vSmarts")
                if reqs:
                    self.log_debug(f'Attach requests processed: {reqs}')
                else:
                    self.log_info('No vSmart attachments needed')

                # Activate vSmart policy
                if not self.is_dryrun:
                    _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy
                    action_list = self.activate_policy(api, target_policies.get(policy_name), policy_name)
                    if len(action_list) == 0:
                        self.log_info('No vSmart policy to activate')
                    else:
                        self.wait_actions(api, action_list, 'activating vSmart policy', raise_on_failure=True)
            except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                self.log_critical(f'Attach failed: {ex}')

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


class RestoreArgs(TaskArgs):
    workdir: str
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    dryrun: bool = False
    attach: bool = False
    update: bool = False
    tag: str

    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)
    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_tag = validator('tag', allow_reuse=True)(validate_catalog_tag)
