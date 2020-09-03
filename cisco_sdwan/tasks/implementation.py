"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.implementation
 This module contains the implementation of user-facing tasks
"""
__all__ = ['TaskBackup', 'TaskRestore', 'TaskDelete', 'TaskCertificate', 'TaskList', 'TaskShowTemplate',
           'TaskMigrate', 'TaskReport']

import argparse
from pathlib import Path
from uuid import uuid4
from collections import namedtuple
from datetime import date
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import RestAPIException, is_version_newer
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import UpdateEval, filename_safe, update_ids, ServerInfo, ExtendedTemplate
from cisco_sdwan.base.models_vmanage import (DeviceConfig, DeviceConfigRFS, DeviceTemplate, DeviceTemplateAttached,
                                             DeviceTemplateValues, DeviceTemplateIndex, FeatureTemplate,
                                             FeatureTemplateIndex, PolicyVsmartIndex, EdgeInventory, ControlInventory,
                                             EdgeCertificate, EdgeCertificateSync, SettingsVbond)
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.migration import factory_cedge_aaa, factory_cedge_global
from cisco_sdwan.migration.feature_migration import FeatureProcessor
from cisco_sdwan.migration.device_migration import DeviceProcessor
from .utils import (TaskOptions, TagOptions, existing_file_type, filename_type, regex_type, uuid_type,
                    version_type, default_workdir, ext_template_type)
from .common import regex_search, clean_dir, Task, TaskArgs, Table, WaitActionsException, TaskException


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nBackup task:')
        task_parser.prog = f'{task_parser.prog} backup'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=filename_type,
                                 default=default_workdir(target_address),
                                 help='Backup destination (default: %(default)s).')
        task_parser.add_argument('--no-rollover', action='store_true',
                                 help='By default, if workdir already exists (before a new backup is saved) the old '
                                      'workdir is renamed using a rolling naming scheme. This option disables this '
                                      'automatic rollover.')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression matching item names to be backed up, within selected tags.')
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='One or more tags for selecting items to be backed up. Multiple tags should be '
                                      f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                      f'"{CATALOG_TAG_ALL}" selects all items, including WAN edge certificates and '
                                      'device configurations.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api, task_output=None):
        self.log_info('Starting backup: vManage URL: "%s" -> Local workdir: "%s"', api.base_url, parsed_args.workdir)

        # Backup workdir must be empty for a new backup
        saved_workdir = clean_dir(parsed_args.workdir, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_workdir:
            self.log_info('Previous backup under "%s" was saved as "%s"', parsed_args.workdir, saved_workdir)

        target_info = ServerInfo(server_version=api.server_version)
        if target_info.save(parsed_args.workdir):
            self.log_info('Saved vManage server information')

        # Backup items not registered to the catalog, but to be included when tag is 'all'
        if CATALOG_TAG_ALL in parsed_args.tags:
            edge_certs = EdgeCertificate.get(api)
            if edge_certs is None:
                self.log_error('Failed backup WAN edge certificates')
            elif edge_certs.save(parsed_args.workdir):
                self.log_info('Saved WAN edge certificates')

            for inventory, info in ((EdgeInventory.get(api), 'WAN edge'), (ControlInventory.get(api), 'controller')):
                if inventory is None:
                    self.log_error('Failed retrieving %s inventory', info)
                    continue

                for uuid, _, hostname, _ in inventory.extended_iter():
                    if hostname is None:
                        self.log_debug('Skipping %s, no hostname', uuid)
                        continue

                    for item, config_type in ((DeviceConfig.get(api, DeviceConfig.api_params(uuid)), 'CFS'),
                                              (DeviceConfigRFS.get(api, DeviceConfigRFS.api_params(uuid)), 'RFS')):
                        if item is None:
                            self.log_error('Failed backup %s device configuration %s', config_type, hostname)
                            continue
                        if item.save(parsed_args.workdir, item_name=hostname, item_id=uuid):
                            self.log_info('Done %s device configuration %s', config_type, hostname)

        # Backup items registered to the catalog
        for _, info, index_cls, item_cls in catalog_iter(*parsed_args.tags, version=api.server_version):
            item_index = index_cls.get(api)
            if item_index is None:
                self.log_debug('Skipped %s, item not supported by this vManage', info)
                continue
            if item_index.save(parsed_args.workdir):
                self.log_info('Saved %s index', info)

            matched_item_iter = (
                (item_id, item_name) for item_id, item_name in item_index
                if parsed_args.regex is None or regex_search(parsed_args.regex, item_name)
            )
            for item_id, item_name in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    self.log_error('Failed backup %s %s', info, item_name)
                    continue
                if item.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                    self.log_info('Done %s %s', info, item_name)

                # Special case for DeviceTemplateAttached and DeviceTemplateValues
                if isinstance(item, DeviceTemplate):
                    devices_attached = DeviceTemplateAttached.get(api, item_id)
                    if devices_attached is None:
                        self.log_error('Failed backup %s %s attached devices', info, item_name)
                        continue
                    if devices_attached.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                        self.log_info('Done %s %s attached devices', info, item_name)
                    else:
                        self.log_debug('Skipped %s %s attached devices, none found', info, item_name)
                        continue

                    try:
                        uuid_list = [uuid for uuid, _ in devices_attached]
                        values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(item_id, uuid_list),
                                                               DeviceTemplateValues.api_path.post))
                        if values.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                            self.log_info('Done %s %s values', info, item_name)
                    except RestAPIException as ex:
                        self.log_error('Failed backup %s %s values: %s', info, item_name, ex)


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nRestore task:')
        task_parser.prog = f'{task_parser.prog} restore'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 default=default_workdir(target_address),
                                 help='Restore source (default: %(default)s).')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression matching item names to be restored, within selected tags.')
        xor_group = task_parser.add_mutually_exclusive_group(required=False)
        xor_group.add_argument('--dryrun', action='store_true',
                               help='Dry-run mode. Items to be restored are listed but not pushed to vManage.')
        xor_group.add_argument('--attach', action='store_true',
                               help='Attach devices to templates and activate vSmart policy after restoring items.')
        task_parser.add_argument('--force', action='store_true',
                                 help='Target vManage items with the same name as the corresponding item in workdir '
                                      'are updated with the contents from workdir. Without this option, those items '
                                      'are skipped and not overwritten.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='Tag for selecting items to be restored. Items that are dependencies of the '
                                      'specified tag are automatically included. Available tags: '
                                      f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api, task_output=None):
        def load_items(index, item_cls):
            item_iter = (
                (item_id, item_cls.load(parsed_args.workdir, index.need_extended_name, item_name, item_id))
                for item_id, item_name in index
            )
            return ((item_id, item_obj) for item_id, item_obj in item_iter if item_obj is not None)

        self.log_info('Starting restore%s: Local workdir: "%s" -> vManage URL: "%s"',
                      ', DRY-RUN mode' if parsed_args.dryrun else '', parsed_args.workdir, api.base_url)

        local_info = ServerInfo.load(parsed_args.workdir)
        # Server info file may not be present (e.g. backup from older Sastre releases)
        if local_info is not None and is_version_newer(api.server_version, local_info.server_version):
            self.log_warning('Target vManage release (%s) is older than the release used in backup (%s). '
                             'Items may fail to be restored due to incompatibilities across releases.',
                             api.server_version, local_info.server_version)
        vbond = SettingsVbond.get(api)
        if vbond is None:
            self.log_warning('Failed retrieving vBond settings. Restoring template_device items will fail if vBond '
                             'is not configured.')

        self.log_info('Loading existing items from target vManage')
        target_all_items_map = {
            hash(type(index)): {item_name: item_id for item_id, item_name in index}
            for _, _, index, item_cls in self.index_iter(api, catalog_iter(CATALOG_TAG_ALL, version=api.server_version))
        }

        self.log_info('Identifying items to be pushed')
        id_mapping = {}         # {<old_id>: <new_id>}, used to replace old (saved) item ids with new (target) ids
        restore_list = []       # [ (<info>, <index_cls>, [(<item_id>, <item>, <id_on_target>), ...]), ...]
        dependency_set = set()  # {<item_id>, ...}
        match_set = set()       # {<item_id>, ...}
        for tag in ordered_tags(parsed_args.tag):
            if tag == 'template_device' and vbond is not None and not vbond.is_configured:
                self.log_warning('Will skip %s items because vBond is not configured. '
                                 'On vManage, Administration > Settings > vBond.', tag)
                continue

            self.log_info('Inspecting %s items', tag)
            tag_iter = (
                (info, index, load_items(index, item_cls))
                for _, info, index, item_cls in self.index_iter(parsed_args.workdir,
                                                                catalog_iter(tag, version=api.server_version))
            )
            for info, index, loaded_items_iter in tag_iter:
                target_item_map = target_all_items_map.get(hash(type(index)))
                if target_item_map is None:
                    # Logging at warning level because the backup files did have this item
                    self.log_warning('Will skip %s, item not supported by target vManage', info)
                    continue

                restore_item_list = []
                for item_id, item in loaded_items_iter:
                    target_id = target_item_map.get(item.name)
                    if target_id is not None:
                        # Item already exists on target vManage, record item id from target
                        if item_id != target_id:
                            id_mapping[item_id] = target_id

                        if not parsed_args.force:
                            # Existing item on target vManage will be used, i.e. will not overwrite it
                            self.log_debug('Will skip %s %s, item already on target vManage', info, item.name)
                            continue

                    if item.is_readonly:
                        self.log_debug('Will skip read-only %s %s', info, item.name)
                        continue

                    item_matches = (
                        (parsed_args.tag == CATALOG_TAG_ALL or parsed_args.tag == tag) and
                        (parsed_args.regex is None or regex_search(parsed_args.regex, item.name))
                    )
                    if item_matches:
                        match_set.add(item_id)
                    if item_matches or item_id in dependency_set:
                        # A target_id that is not None signals a put operation, as opposed to post.
                        # target_id will be None unless --force is specified and item name is on target
                        restore_item_list.append((item_id, item, target_id))
                        dependency_set.update(item.id_references_set)

                if len(restore_item_list) > 0:
                    restore_list.append((info, index, restore_item_list))

        log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''
        if len(restore_list) > 0:
            self.log_info('%sPushing items to vManage', log_prefix)
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
                            if parsed_args.dryrun:
                                self.log_info('%s%s %s %s%s', log_prefix, op_info, info, item.name, reason)
                                continue
                            # Not using item id returned from post because post can return empty (e.g. local policies)
                            api.post(item.post_data(id_mapping), item.api_path.post)
                            pushed_item_dict[item.name] = item_id
                        else:
                            # Update existing item
                            update_data = item.put_data(id_mapping)
                            if item.get_raise(api, target_id).is_equal(update_data):
                                self.log_debug('%s%s skipped (no diffs) %s %s', log_prefix, op_info, info, item.name)
                                continue

                            if parsed_args.dryrun:
                                self.log_info('%s%s %s %s%s', log_prefix, op_info, info, item.name, reason)
                                continue

                            put_eval = UpdateEval(api.put(update_data, item.api_path.put, target_id))
                            if put_eval.need_reattach:
                                if put_eval.is_master:
                                    self.log_info('Updating %s %s requires reattach', info, item.name)
                                    action_list = self.attach_template(api, parsed_args.workdir,
                                                                       index.need_extended_name,
                                                                       [(item.name, item_id, target_id)])
                                else:
                                    self.log_info('Updating %s %s requires reattach of affected templates',
                                                  info, item.name)
                                    target_templates = {item_id: item_name
                                                        for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                                    templates_iter = (
                                        (target_templates[tgt_id], tgt_id)
                                        for tgt_id in put_eval.templates_affected_iter()
                                    )
                                    action_list = self.reattach_template(api, templates_iter)
                                self.wait_actions(api, action_list, 'reattaching templates', raise_on_failure=True)
                            elif put_eval.need_reactivate:
                                self.log_info('Updating %s %s requires vSmart policy reactivate', info, item.name)
                                action_list = self.activate_policy(
                                    api, *PolicyVsmartIndex.get_raise(api).active_policy, is_edited=True
                                )
                                self.wait_actions(api, action_list, 'reactivating vSmart policy', raise_on_failure=True)
                    except (RestAPIException, WaitActionsException) as ex:
                        self.log_error('Failed %s %s %s%s: %s', op_info, info, item.name, reason, ex)
                    else:
                        self.log_info('Done: %s %s %s%s', op_info, info, item.name, reason)

                # Read new ids from target and update id_mapping
                try:
                    new_target_item_map = {item_name: item_id for item_id, item_name in index.get_raise(api)}
                    for item_name, old_item_id in pushed_item_dict.items():
                        id_mapping[old_item_id] = new_target_item_map[item_name]
                except RestAPIException as ex:
                    self.log_critical('Failed retrieving %s: %s', info, ex)
                    break
        else:
            self.log_info('%sNo items to push', log_prefix)

        if parsed_args.attach:
            try:
                target_templates = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                target_policies = {item_name: item_id for item_id, item_name in PolicyVsmartIndex.get_raise(api)}
                saved_template_index = DeviceTemplateIndex.load(parsed_args.workdir, raise_not_found=True)
                attach_common_args = (api, parsed_args.workdir, saved_template_index.need_extended_name)
                # Attach WAN Edge templates
                edge_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart)
                )
                wan_edge_set = {uuid for uuid, _ in EdgeInventory.get_raise(api)}
                action_list = self.attach_template(*attach_common_args, edge_templates_iter, wan_edge_set)
                if len(action_list) == 0:
                    self.log_info('No WAN Edge attachments needed')
                else:
                    self.wait_actions(api, action_list, 'attaching WAN Edge templates')
                # Attach vSmart template
                vsmart_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart)
                )
                vsmart_set = {
                    uuid for uuid, _ in ControlInventory.get_raise(api).filtered_iter(ControlInventory.is_vsmart)
                }
                action_list = self.attach_template(*attach_common_args, vsmart_templates_iter, vsmart_set)
                if len(action_list) == 0:
                    self.log_info('No vSmart attachments needed')
                else:
                    self.wait_actions(api, action_list, 'attaching vSmart template')
                # Activate vSmart policy
                _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy
                action_list = self.activate_policy(api, target_policies.get(policy_name), policy_name)
                if len(action_list) == 0:
                    self.log_info('No vSmart policy to activate')
                else:
                    self.wait_actions(api, action_list, 'activating vSmart policy')
            except (RestAPIException, FileNotFoundError) as ex:
                self.log_critical('Attach failed: %s', ex)


@TaskOptions.register('delete')
class TaskDelete(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nDelete task:')
        task_parser.prog = f'{task_parser.prog} delete'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression matching item names to be deleted, within selected tags.')
        xor_group = task_parser.add_mutually_exclusive_group(required=False)
        xor_group.add_argument('--dryrun', action='store_true',
                               help='Dry-run mode. Items matched for removal are listed but not deleted.')
        xor_group.add_argument('--detach', action='store_true',
                               help='USE WITH CAUTION! Detach devices from templates and deactivate vSmart policy '
                                    'before deleting items. This allows deleting items that are associated with '
                                    'attached templates and active policies.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='Tag for selecting items to be deleted. Available tags: '
                                      f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api, task_output=None):
        self.log_info('Starting delete%s: vManage URL: "%s"',
                      ', DRY-RUN mode' if parsed_args.dryrun else '', api.base_url)

        if parsed_args.detach:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)
                # Detach WAN Edge templates
                action_list = self.detach_template(api, template_index, DeviceTemplateIndex.is_not_vsmart)
                if len(action_list) == 0:
                    self.log_info('No WAN Edge attached')
                else:
                    self.wait_actions(api, action_list, 'detaching WAN Edge templates')
                # Deactivate vSmart policy
                action_list = self.deactivate_policy(api)
                if len(action_list) == 0:
                    self.log_info('No vSmart policy activated')
                else:
                    self.wait_actions(api, action_list, 'deactivating vSmart policy')
                # Detach vSmart template
                action_list = self.detach_template(api, template_index, DeviceTemplateIndex.is_vsmart)
                if len(action_list) == 0:
                    self.log_info('No vSmart attached')
                else:
                    self.wait_actions(api, action_list, 'detaching vSmart template')
            except RestAPIException as ex:
                self.log_critical('Detach failed: %s', ex)

        for tag in ordered_tags(parsed_args.tag, parsed_args.tag != CATALOG_TAG_ALL):
            self.log_info('Inspecting %s items', tag)
            matched_item_iter = (
                (item_name, item_id, item_cls, info)
                for _, info, index, item_cls in self.index_iter(api, catalog_iter(tag, version=api.server_version))
                for item_id, item_name in index
                if parsed_args.regex is None or regex_search(parsed_args.regex, item_name)
            )
            for item_name, item_id, item_cls, info in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    self.log_warning('Failed retrieving %s %s', info, item_name)
                    continue
                if item.is_readonly or item.is_system:
                    self.log_debug('Skipped %s %s %s', 'read-only' if item.is_readonly else 'system', info, item_name)
                    continue
                if parsed_args.dryrun:
                    self.log_info('DRY-RUN: Delete %s %s', info, item_name)
                    continue

                if api.delete(item_cls.api_path.delete, item_id):
                    self.log_info('Done: Delete %s %s', info, item_name)
                else:
                    self.log_warning('Failed deleting %s %s', info, item_name)


@TaskOptions.register('certificate')
class TaskCertificate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nCertificate task:')
        task_parser.prog = f'{task_parser.prog} certificate'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='commands', dest='command',
                                               help='Define source of WAN edge certificate validity status.')
        sub_tasks.required = True

        restore_parser = sub_tasks.add_parser('restore', help='Restore status from backup.')
        restore_parser.set_defaults(source_iter=TaskCertificate.restore_iter)
        restore_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                    default=default_workdir(target_address),
                                    help='Restore source (default: %(default)s).')

        set_parser = sub_tasks.add_parser('set', help='Set status to provided value.')
        set_parser.set_defaults(source_iter=TaskCertificate.set_iter)
        set_parser.add_argument('status', choices=['invalid', 'staging', 'valid'],
                                help='WAN edge certificate status.')

        # Parameters common to all sub-tasks
        for sub_task in (restore_parser, set_parser):
            sub_task.add_argument('--regex', metavar='<regex>', type=regex_type,
                                  help='Regular expression selecting devices to modify certificate status. Matches on '
                                       'the hostname or chassis/uuid. Use "^-$" to match devices without a hostname.')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='Dry-run mode. List modifications that would be performed without pushing '
                                       'changes to vManage.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def restore_iter(target_certs, parsed_args):
        saved_certs = EdgeCertificate.load(parsed_args.workdir)
        if saved_certs is None:
            raise FileNotFoundError('WAN edge certificates were not found in the backup')

        saved_certs_dict = {uuid: status for uuid, status in saved_certs}

        return (
            (uuid, status, hostname, saved_certs_dict[uuid])
            for uuid, status, hostname, chassis, serial, state in target_certs.extended_iter()
            if uuid in saved_certs_dict
        )

    @staticmethod
    def set_iter(target_certs, parsed_args):
        return (
            (uuid, status, hostname, parsed_args.status)
            for uuid, status, hostname, chassis, serial, state in target_certs.extended_iter()
        )

    def runner(self, parsed_args, api, task_output=None):
        if parsed_args.command == 'restore':
            start_msg = f'Restore status workdir: "{parsed_args.workdir}" -> vManage URL: "{api.base_url}"'
        else:
            start_msg = f'Set status to "{parsed_args.status}" -> vManage URL: "{api.base_url}"'
        self.log_info('Starting certificate%s: %s', ', DRY-RUN mode' if parsed_args.dryrun else '', start_msg)

        try:
            self.log_info('Loading WAN edge certificate list from target vManage')
            target_certs = EdgeCertificate.get_raise(api)

            matched_items = (
                (uuid, current_status, hostname, new_status)
                for uuid, current_status, hostname, new_status in parsed_args.source_iter(target_certs, parsed_args)
                if parsed_args.regex is None or regex_search(parsed_args.regex, hostname or '-', uuid)
            )
            update_list = []
            self.log_info('Identifying items to be pushed')
            log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''
            for uuid, current_status, hostname, new_status in matched_items:
                if current_status == new_status:
                    self.log_debug('%sSkipping %s, no changes', log_prefix, hostname or uuid)
                    continue

                self.log_info('%sWill update %s status: %s -> %s',
                              log_prefix, hostname or uuid, current_status, new_status)
                update_list.append((uuid, new_status))

            if len(update_list) > 0:
                self.log_info('%sPushing certificate status changes to vManage', log_prefix)
                if not parsed_args.dryrun:
                    api.post(target_certs.status_post_data(*update_list), EdgeCertificate.api_path.post)
                    action_worker = EdgeCertificateSync(api.post({}, EdgeCertificateSync.api_path.post))
                    self.wait_actions(api, [(action_worker, None)], 'certificate sync with controllers',
                                      raise_on_failure=True)
            else:
                self.log_info('%sNo certificate status updates to push', log_prefix)

        except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
            self.log_critical('Failed updating WAN edge certificate status: %s', ex)


@TaskOptions.register('list')
class TaskList(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nList task:')
        task_parser.prog = f'{task_parser.prog} list'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='options', dest='option', help='list options')
        sub_tasks.required = True

        config_parser = sub_tasks.add_parser('configuration', aliases=['config'], help='List configuration items.')
        config_parser.set_defaults(table_factory=TaskList.config_table)
        config_parser.set_defaults(subtask_info='list configuration')
        config_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                   help='One or more tags for selecting groups of items. Multiple tags should be '
                                        f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                        f'"{CATALOG_TAG_ALL}" selects all items.')
        config_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                   help='Regular expression selecting items to list. Match on item names or item IDs.')

        cert_parser = sub_tasks.add_parser('certificate', aliases=['cert'], help='List certificates.')
        cert_parser.set_defaults(table_factory=TaskList.cert_table)
        cert_parser.set_defaults(subtask_info='list certificates')
        cert_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression selecting devices to list. Match on hostname or '
                                      'chassis/uuid. Use "^-$" to match devices without a hostname.')

        xform_parser = sub_tasks.add_parser('transform',
                                            help='List name transformations performed by a name-regex against '
                                                 'existing item names.')
        xform_parser.set_defaults(table_factory=TaskList.xform_table)
        xform_parser.set_defaults(subtask_info='test name-regex')
        xform_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                  help='One or more tags for selecting groups of items. Multiple tags should be '
                                       f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                       f'"{CATALOG_TAG_ALL}" selects all items.')
        xform_parser.add_argument('name_regex', metavar='<name-regex>', type=ext_template_type,
                                  help='Name-regex used to transform an existing item name. Variable {name} is '
                                       'replaced with the original template name. Sections of the original template '
                                       'name can be selected using the {name <regex>} format. Where <regex> is a '
                                       'regular expression that must contain at least one capturing group. Capturing '
                                       'groups identify sections of the original name to keep.')
        xform_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                  help='Regular expression selecting items to list. Match on original item names')

        # Parameters common to all sub-tasks
        for sub_task in (config_parser, cert_parser, xform_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                  help='If provided, list will read from the specified directory instead of the ' 
                                       'target vManage.')
            sub_task.add_argument('--csv', metavar='<filename>', type=filename_type, help='Export table as a csv file.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    def runner(self, parsed_args, api=None, task_output=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info('Starting %s: %s', parsed_args.subtask_info, source_info)

        results = parsed_args.table_factory(self, parsed_args, api)
        self.log_info('List criteria matched %s items', len(results))

        if len(results) > 0:
            if parsed_args.csv is not None:
                results.save(parsed_args.csv)
                self.log_info('Table exported as %s', parsed_args.csv)
            elif task_output is not None:
                task_output.extend(results.pretty_iter())
            else:
                print('\n'.join(results.pretty_iter()))

    def config_table(self, parsed_args, api):
        backend = api or parsed_args.workdir
        # Only perform version-based filtering if backend is api
        version = None if api is None else api.server_version

        matched_item_iter = (
            (item_name, item_id, tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter(*parsed_args.tags, version=version))
            for item_id, item_name in index
            if parsed_args.regex is None or regex_search(parsed_args.regex, item_name, item_id)
        )
        results = Table('Name', 'ID', 'Tag', 'Type')
        results.extend(matched_item_iter)

        return results

    def cert_table(self, parsed_args, api):
        if api is None:
            certs = EdgeCertificate.load(parsed_args.workdir)
            if certs is None:
                raise FileNotFoundError('WAN edge certificates were not found in the backup')
        else:
            certs = EdgeCertificate.get_raise(api)

        matched_item_iter = (
            (hostname or '-', chassis, serial, EdgeCertificate.state_str(state), status)
            for uuid, status, hostname, chassis, serial, state in certs.extended_iter()
            if parsed_args.regex is None or regex_search(parsed_args.regex, hostname or '-', uuid)
        )
        results = Table('Hostname', 'Chassis', 'Serial', 'State',  'Status')
        results.extend(matched_item_iter)

        return results

    def xform_table(self, parsed_args, api):
        backend = api or parsed_args.workdir
        # Only perform version-based filtering if backend is api
        version = None if api is None else api.server_version

        name_regex = ExtendedTemplate(parsed_args.name_regex)
        matched_item_iter = (
            (item_name,  name_regex(item_name), tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter(*parsed_args.tags, version=version))
            for item_id, item_name in index
            if parsed_args.regex is None or regex_search(parsed_args.regex, item_name)
        )
        results = Table('Name', 'Transformed', 'Tag', 'Type')
        results.extend(matched_item_iter)

        return results


@TaskOptions.register('show-template')
class TaskShowTemplate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nShow template task:')
        task_parser.prog = f'{task_parser.prog} show-template'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='options', dest='option', help='show-template options')
        sub_tasks.required = True

        values_parser = sub_tasks.add_parser('values', help='Show values from template attachments.')
        values_parser.set_defaults(table_factory=TaskShowTemplate.values_table)
        values_parser.set_defaults(subtask_info='values')
        xor_group = values_parser.add_mutually_exclusive_group(required=True)
        xor_group.add_argument('--name', metavar='<name>', help='Device template name.')
        xor_group.add_argument('--id', metavar='<id>', type=uuid_type, help='Device template ID.')
        xor_group.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='Regular expression matching device template names.')
        values_parser.add_argument('--csv', metavar='<directory>', type=filename_type,
                                   help='Export tables as csv files under the specified directory.')

        references_parser = sub_tasks.add_parser('references', aliases=['ref'],
                                                 help='Show device templates that reference a feature template.')
        references_parser.set_defaults(table_factory=TaskShowTemplate.references_table)
        references_parser.set_defaults(subtask_info='references')
        references_parser.add_argument('--with-refs', action='store_true',
                                       help='Include only feature-templates with device-template references.')
        references_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                       help='Regular expression matching feature template names to include.')
        references_parser.add_argument('--csv', metavar='<filename>', type=filename_type,
                                       help='Export table as a csv file.')

        # Parameters common to all sub-tasks
        for sub_task in (values_parser, references_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                  help='If provided, show-template will read from the specified directory instead of '
                                       'the target vManage.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    def runner(self, parsed_args, api=None, task_output=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info('Starting show-template %s: %s', parsed_args.subtask_info, source_info)

        # Dispatch to the appropriate show handler
        parsed_args.table_factory(self, parsed_args, api, task_output)

    def values_table(self, parsed_args, api, task_output):
        def item_matches(item_name, item_id):
            if parsed_args.id is not None:
                return item_id == parsed_args.id
            if parsed_args.name is not None:
                return item_name == parsed_args.name
            return regex_search(parsed_args.regex, item_name)

        def template_values(ext_name, template_name, template_id):
            if api is None:
                # Load from local backup
                values = DeviceTemplateValues.load(parsed_args.workdir, ext_name, template_name, template_id)
                if values is None:
                    self.log_debug('Skipped %s. No template values file found.', template_name)
            else:
                # Load from vManage via API
                devices_attached = DeviceTemplateAttached.get(api, template_id)
                if devices_attached is None:
                    self.log_error('Failed to retrieve %s attached devices', template_name)
                    return None

                try:
                    uuid_list = [uuid for uuid, _ in devices_attached]
                    values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(template_id, uuid_list),
                                                           DeviceTemplateValues.api_path.post))
                except RestAPIException:
                    self.log_error('Failed to retrieve %s values', template_name)
                    return None

            return values

        if parsed_args.csv is not None:
            Path(parsed_args.csv).mkdir(parents=True, exist_ok=True)

        print_buffer = []
        backend = api or parsed_args.workdir
        matched_item_iter = (
            (index.need_extended_name, item_name, item_id, tag, info)
            for tag, info, index, item_cls in self.index_iter(backend, catalog_iter('template_device'))
            for item_id, item_name in index
            if item_matches(item_name, item_id) and issubclass(item_cls, DeviceTemplate)
        )
        for use_ext_name, item_name, item_id, tag, info in matched_item_iter:
            attached_values = template_values(use_ext_name, item_name, item_id)
            if attached_values is None:
                continue

            self.log_info('Inspecting %s %s values', info, item_name)
            var_names = attached_values.title_dict()
            for csv_id, csv_name, entry in attached_values:
                print_grp = [
                    'Template {name}, device {device}:'.format(name=item_name, device=csv_name or csv_id)
                ]
                results = Table('Name', 'Value', 'Variable')
                results.extend(
                    (var_names.get(var, '<not found>'), value, var) for var, value in entry.items()
                )
                if len(results) > 0:
                    if parsed_args.csv is not None:
                        filename = 'template_values_{name}_{id}.csv'.format(name=filename_safe(item_name, lower=True),
                                                                            id=csv_name or csv_id)
                        results.save(Path(parsed_args.csv, filename))
                    print_grp.extend(results.pretty_iter())
                print_buffer.append('\n'.join(print_grp))

        if len(print_buffer) > 0:
            if parsed_args.csv is not None:
                self.log_info('Files saved under directory %s', parsed_args.csv)
            elif task_output is not None:
                task_output.extend(print_buffer)
            else:
                print('\n\n'.join(print_buffer))
        else:
            match_type = 'ID' if parsed_args.id is not None else 'name' if parsed_args.name is not None else 'regex'
            self.log_warning('No items found with the %s provided', match_type)

    def references_table(self, parsed_args, api, task_output):
        FeatureInfo = namedtuple('FeatureInfo', ['name', 'type', 'attached', 'device_templates'])

        backend = api or parsed_args.workdir
        self.log_info('Inspecting feature templates')
        feature_index = self.index_get(FeatureTemplateIndex, backend)
        feature_dict = {}
        for item_id, item_name in feature_index:
            feature = self.item_get(FeatureTemplate, backend, item_id, item_name, feature_index.need_extended_name)
            if feature is None:
                self.log_error('Failed to load feature template %s', item_name)
                continue

            feature_dict[item_id] = FeatureInfo(item_name, feature.type, feature.devices_attached, set())

        self.log_info('Inspecting device templates')
        device_index = self.index_get(DeviceTemplateIndex, backend)
        for item_id, item_name in device_index:
            device = self.item_get(DeviceTemplate, backend, item_id, item_name, device_index.need_extended_name)
            if device is None:
                self.log_error('Failed to load device template %s', item_name)
                continue
            if device.is_type_cli:
                continue

            for feature_id in device.feature_templates:
                feature_info = feature_dict.get(feature_id)
                if feature_info is None:
                    self.log_warning('Template %s references a non-existing feature template: %s',
                                     item_name, feature_id)
                    continue

                feature_info.device_templates.add(item_name)

        self.log_info('Creating references table')
        results = Table('Feature Template', 'Type', 'Devices Attached', 'Device Templates')
        matched_item_iter = (feature_info for feature_info in feature_dict.values()
                             if parsed_args.regex is None or regex_search(parsed_args.regex, feature_info.name))
        for feature_info in matched_item_iter:
            if not parsed_args.with_refs and not feature_info.device_templates:
                results.add_marker()
                results.add(feature_info.name, feature_info.type, str(feature_info.attached), '')
                continue

            for seq, device_template in enumerate(feature_info.device_templates):
                if seq == 0:
                    results.add_marker()
                    results.add(feature_info.name, feature_info.type, str(feature_info.attached), device_template)
                else:
                    results.add('', '', '', device_template)

        if len(results) > 0:
            if parsed_args.csv is not None:
                results.save(parsed_args.csv)
                self.log_info('Table exported as %s', parsed_args.csv)
            elif task_output is not None:
                task_output.extend(results.pretty_iter())
            else:
                print('\n'.join(results.pretty_iter()))
        else:
            self.log_warning('Table is empty, no items matched the criteria.')


@TaskOptions.register('migrate')
class TaskMigrate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nMigrate task:')
        task_parser.prog = f'{task_parser.prog} migrate'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('scope', choices=['all', 'attached'],
                                 help='Select whether to evaluate all feature templates, or only feature templates '
                                      'attached to device templates.')
        task_parser.add_argument('output', metavar='<directory>', type=filename_type,
                                 help='Directory to save migrated templates.')
        task_parser.add_argument('--no-rollover', action='store_true',
                                 help='By default, if the output directory already exists it is renamed using a '
                                      'rolling naming scheme. This option disables this automatic rollover.')
        task_parser.add_argument('--name', metavar='<format>', type=ext_template_type, default='migrated_{name}',
                                 help='Format used to name the migrated templates (default: %(default)s). '
                                      'Variable {name} is replaced with the original template name. Sections of the '
                                      'original template name can be selected using the {name <regex>} format. Where '
                                      '<regex> is a regular expression that must contain at least one capturing group. '
                                      'Capturing groups identify sections of the original name to keep.')
        task_parser.add_argument('--from', metavar='<version>', type=version_type, dest='from_version', default='18.4',
                                 help='vManage version from source templates (default: %(default)s).')
        task_parser.add_argument('--to', metavar='<version>', type=version_type, dest='to_version', default='20.1',
                                 help='Target vManage version for template migration (default: %(default)s).')
        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 help='If provided, migrate will read from the specified directory. '
                                      'Otherwise it reads from the target vManage.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    def runner(self, parsed_args, api=None, task_output=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info('Starting migrate: %s %s -> %s Local output dir: "%s"', source_info, parsed_args.from_version,
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

                        try:
                            item_processor = loaded_processors.get(item_cls)
                            if item_processor is None:
                                raise StopProcessorException()

                            self.log_debug('Evaluating %s %s', info, item_name)
                            if not item_processor.is_in_scope(item, migrate_all=(parsed_args.scope == 'all')):
                                self.log_debug('Skipping %s, migration not necessary', item_name)
                                raise StopProcessorException()

                            new_name, is_valid = item.get_new_name(parsed_args.name)
                            if not is_valid:
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

                        except StopProcessorException:
                            pass

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


@TaskOptions.register('report')
class TaskReport(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nReport task:')
        task_parser.prog = f'{task_parser.prog} report'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--file', metavar='<filename>', type=filename_type,
                                 default=f'report_{date.today():%Y%m%d}.txt',
                                 help='Report filename (default: %(default)s).')
        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 help='If provided, report will read from the specified directory instead of the '
                                      'target vManage.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    def runner(self, parsed_args, api=None, task_output=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info('Starting report: %s -> "%s"', source_info, parsed_args.file)

        report_config_tasks = [
            (f'### List configuration {tag} ###', TaskList,
             TaskArgs(csv=None, option='configuration', regex=None, subtask_info='list configuration',
                      table_factory=TaskList.config_table, tags=[tag], workdir=parsed_args.workdir))
            for tag in ordered_tags(CATALOG_TAG_ALL)
        ]
        report_tasks = [
            ('### List certificate ###', TaskList,
             TaskArgs(csv=None, option='certificate', regex=None, subtask_info='list certificate',
                      table_factory=TaskList.cert_table, workdir=parsed_args.workdir)),
            ('### Show-template values ###', TaskShowTemplate,
             TaskArgs(csv=None, id=None, name=None, option='values', regex='.+', subtask_info='values',
                      table_factory=TaskShowTemplate.values_table, workdir=parsed_args.workdir)),
            ('### Show-template references ###', TaskShowTemplate,
             TaskArgs(csv=None, option='references', regex=None, with_refs=False, subtask_info='references',
                      table_factory=TaskShowTemplate.references_table, workdir=parsed_args.workdir)),
        ]

        report_buffer = []
        for task_header, task, task_args in report_config_tasks + report_tasks:
            try:
                task_buffer = []
                task().runner(task_args, api, task_output=task_buffer)
                if task_buffer:
                    report_buffer.extend([task_header] + task_buffer + [''])
            except (TaskException, FileNotFoundError) as ex:
                self.log_error(f'Task {task.__name__} error: {ex}')

        with open(parsed_args.file, 'w') as f:
            f.write('\n'.join(report_buffer))
