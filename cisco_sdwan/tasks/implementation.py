"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.implementation
 This module contains the implementation of user-facing tasks
"""
__all__ = ['TaskBackup', 'TaskRestore', 'TaskDelete', 'TaskCertificate', 'TaskList', 'TaskShowTemplate']

import argparse
from shutil import rmtree
from pathlib import Path
from uuid import uuid4
from datetime import date
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import RestAPIException, is_version_newer
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import UpdateEval, filename_safe, update_ids, DATA_DIR, ServerInfo
from cisco_sdwan.base.models_vmanage import (DeviceTemplate, DeviceTemplateAttached, DeviceTemplateValues,
                                             DeviceTemplateIndex, FeatureTemplate, PolicyVsmartIndex, EdgeInventory,
                                             ControlInventory, EdgeCertificate, EdgeCertificateSync, SettingsVbond)
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.migration import factory_cedge_aaa, factory_cedge_global
from cisco_sdwan.migration.feature_migration import FeatureProcessor
from cisco_sdwan.migration.device_migration import DeviceProcessor
from .utils import (TaskOptions, TagOptions, ShowOptions, existing_file_type, filename_type, regex_type, uuid_type,
                    version_type, default_workdir)
from .common import regex_search, Task, Table, WaitActionsException, TaskException


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nBackup task:')
        task_parser.prog = f'{task_parser.prog} backup'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=filename_type,
                                 default=default_workdir(target_address),
                                 help=f'Backup destination (default will be "{default_workdir(target_address)}").')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression matching item names to be backed up, within selected tags.')
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='One or more tags for selecting items to be backed up. Multiple tags should be '
                                      f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                      f'"{CATALOG_TAG_ALL}" selects all items, including WAN edge certificates.')
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, parsed_args, api):
        cls.log_info('Starting backup: vManage URL: "%s" -> Local workdir: "%s"', api.base_url, parsed_args.workdir)

        # Backup workdir must be empty for a new backup
        saved_workdir = cls.clean_workdir(parsed_args.workdir)
        if saved_workdir:
            cls.log_info('Previous backup under "%s" was saved as "%s"', parsed_args.workdir, saved_workdir)

        target_info = ServerInfo(server_version=api.server_version)
        if target_info.save(parsed_args.workdir):
            cls.log_info('Saved vManage server information')

        if CATALOG_TAG_ALL in parsed_args.tags:
            # Items without index files to be included with tag 'all'
            edge_certs = EdgeCertificate.get(api)
            if edge_certs is None:
                cls.log_error('Failed backup WAN edge certificates')
            elif edge_certs.save(parsed_args.workdir):
                cls.log_info('Saved WAN edge certificates')

        for _, info, index_cls, item_cls in catalog_iter(*parsed_args.tags, version=api.server_version):
            item_index = index_cls.get(api)
            if item_index is None:
                cls.log_debug('Skipped %s, item not supported by this vManage', info)
                continue
            if item_index.save(parsed_args.workdir):
                cls.log_info('Saved %s index', info)

            matched_item_iter = (
                (item_id, item_name) for item_id, item_name in item_index
                if parsed_args.regex is None or regex_search(parsed_args.regex, item_name)
            )
            for item_id, item_name in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    cls.log_error('Failed backup %s %s', info, item_name)
                    continue
                if item.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                    cls.log_info('Done %s %s', info, item_name)

                # Special case for DeviceTemplateAttached and DeviceTemplateValues
                if isinstance(item, DeviceTemplate):
                    devices_attached = DeviceTemplateAttached.get(api, item_id)
                    if devices_attached is None:
                        cls.log_error('Failed backup %s %s attached devices', info, item_name)
                        continue
                    if devices_attached.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                        cls.log_info('Done %s %s attached devices', info, item_name)
                    else:
                        cls.log_debug('Skipped %s %s attached devices, none found', info, item_name)
                        continue

                    try:
                        uuid_list = [uuid for uuid, _ in devices_attached]
                        values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(item_id, uuid_list),
                                                               DeviceTemplateValues.api_path.post))
                        if values.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                            cls.log_info('Done %s %s values', info, item_name)
                    except RestAPIException as ex:
                        cls.log_error('Failed backup %s %s values: %s', info, item_name, ex)

    @staticmethod
    def clean_workdir(workdir, max_saved=99):
        workdir_path = Path(DATA_DIR, workdir)
        if workdir_path.exists():
            save_seq = range(max_saved)
            for elem in save_seq:
                save_path = Path(DATA_DIR, '{workdir}_{count}'.format(workdir=workdir, count=elem+1))
                if elem == save_seq[-1]:
                    rmtree(save_path, ignore_errors=True)
                if not save_path.exists():
                    workdir_path.rename(save_path)
                    return save_path.name

        return False


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nRestore task:')
        task_parser.prog = f'{task_parser.prog} restore'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 default=default_workdir(target_address),
                                 help=f'Restore source (default will be "{default_workdir(target_address)}").')
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

    @classmethod
    def runner(cls, parsed_args, api):
        def load_items(index, item_cls):
            item_iter = (
                (item_id, item_cls.load(parsed_args.workdir, index.need_extended_name, item_name, item_id))
                for item_id, item_name in index
            )
            return ((item_id, item_obj) for item_id, item_obj in item_iter if item_obj is not None)

        cls.log_info('Starting restore%s: Local workdir: "%s" -> vManage URL: "%s"',
                     ', DRY-RUN mode' if parsed_args.dryrun else '', parsed_args.workdir, api.base_url)

        local_info = ServerInfo.load(parsed_args.workdir)
        # Server info file may not be present (e.g. backup from older Sastre releases)
        if local_info is not None and is_version_newer(api.server_version, local_info.server_version):
            cls.log_warning('Target vManage release (%s) is older than the release used in backup (%s). '
                            'Items may fail to be restored due to incompatibilities across releases.',
                            api.server_version, local_info.server_version)
        vbond = SettingsVbond.get(api)
        if vbond is None:
            cls.log_warning('Failed retrieving vBond settings. Restoring template_device items will fail if vBond '
                            'is not configured.')

        cls.log_info('Loading existing items from target vManage')
        target_all_items_map = {
            hash(type(index)): {item_name: item_id for item_id, item_name in index}
            for _, _, index, item_cls in cls.index_iter(api, catalog_iter(CATALOG_TAG_ALL, version=api.server_version))
        }

        cls.log_info('Identifying items to be pushed')
        id_mapping = {}         # {<old_id>: <new_id>}, used to replace old (saved) item ids with new (target) ids
        restore_list = []       # [ (<info>, <index_cls>, [(<item_id>, <item>, <id_on_target>), ...]), ...]
        dependency_set = set()  # {<item_id>, ...}
        match_set = set()       # {<item_id>, ...}
        for tag in ordered_tags(parsed_args.tag):
            if tag == 'template_device' and vbond is not None and not vbond.is_configured:
                cls.log_warning('Will skip %s items because vBond is not configured. '
                                'On vManage, Administration > Settings > vBond.', tag)
                continue

            cls.log_info('Inspecting %s items', tag)
            tag_iter = (
                (info, index, load_items(index, item_cls))
                for _, info, index, item_cls in cls.index_iter(parsed_args.workdir,
                                                               catalog_iter(tag, version=api.server_version))
            )
            for info, index, loaded_items_iter in tag_iter:
                target_item_map = target_all_items_map.get(hash(type(index)))
                if target_item_map is None:
                    # Logging at warning level because the backup files did have this item
                    cls.log_warning('Will skip %s, item not supported by target vManage', info)
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
                            cls.log_debug('Will skip %s %s, item already on target vManage', info, item.name)
                            continue

                    if item.is_readonly:
                        cls.log_debug('Will skip read-only %s %s', info, item.name)
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
            cls.log_info('%sPushing items to vManage', log_prefix)
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
                                cls.log_info('%s%s %s %s%s', log_prefix, op_info, info, item.name, reason)
                                continue
                            # Not using item id returned from post because post can return empty (e.g. local policies)
                            api.post(item.post_data(id_mapping), item.api_path.post)
                            pushed_item_dict[item.name] = item_id
                        else:
                            # Update existing item
                            update_data = item.put_data(id_mapping)
                            if item.get_raise(api, target_id).is_equal(update_data):
                                cls.log_debug('%s%s skipped (no diffs) %s %s', log_prefix, op_info, info, item.name)
                                continue

                            if parsed_args.dryrun:
                                cls.log_info('%s%s %s %s%s', log_prefix, op_info, info, item.name, reason)
                                continue

                            put_eval = UpdateEval(api.put(update_data, item.api_path.put, target_id))
                            if put_eval.need_reattach:
                                if put_eval.is_master:
                                    cls.log_info('Updating %s %s requires reattach', info, item.name)
                                    action_list = cls.attach_template(api, parsed_args.workdir,
                                                                      index.need_extended_name,
                                                                      [(item.name, item_id, target_id)])
                                else:
                                    cls.log_info('Updating %s %s requires reattach of affected templates',
                                                 info, item.name)
                                    target_templates = {item_id: item_name
                                                        for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                                    templates_iter = (
                                        (target_templates[tgt_id], tgt_id)
                                        for tgt_id in put_eval.templates_affected_iter()
                                    )
                                    action_list = cls.reattach_template(api, templates_iter)
                                cls.wait_actions(api, action_list, 'reattaching templates', raise_on_failure=True)
                            elif put_eval.need_reactivate:
                                cls.log_info('Updating %s %s requires vSmart policy reactivate', info, item.name)
                                action_list = cls.activate_policy(
                                    api, *PolicyVsmartIndex.get_raise(api).active_policy, is_edited=True
                                )
                                cls.wait_actions(api, action_list, 'reactivating vSmart policy', raise_on_failure=True)
                    except (RestAPIException, WaitActionsException) as ex:
                        cls.log_error('Failed %s %s %s%s: %s', op_info, info, item.name, reason, ex)
                    else:
                        cls.log_info('Done: %s %s %s%s', op_info, info, item.name, reason)

                # Read new ids from target and update id_mapping
                try:
                    new_target_item_map = {item_name: item_id for item_id, item_name in index.get_raise(api)}
                    for item_name, old_item_id in pushed_item_dict.items():
                        id_mapping[old_item_id] = new_target_item_map[item_name]
                except RestAPIException as ex:
                    cls.log_critical('Failed retrieving %s: %s', info, ex)
                    break
        else:
            cls.log_info('%sNo items to push', log_prefix)

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
                action_list = cls.attach_template(*attach_common_args, edge_templates_iter, wan_edge_set)
                if len(action_list) == 0:
                    cls.log_info('No WAN Edge attachments needed')
                else:
                    cls.wait_actions(api, action_list, 'attaching WAN Edge templates')
                # Attach vSmart template
                vsmart_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart)
                )
                vsmart_set = {
                    uuid for uuid, _ in ControlInventory.get_raise(api).filtered_iter(ControlInventory.is_vsmart)
                }
                action_list = cls.attach_template(*attach_common_args, vsmart_templates_iter, vsmart_set)
                if len(action_list) == 0:
                    cls.log_info('No vSmart attachments needed')
                else:
                    cls.wait_actions(api, action_list, 'attaching vSmart template')
                # Activate vSmart policy
                _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy
                action_list = cls.activate_policy(api, target_policies.get(policy_name), policy_name)
                if len(action_list) == 0:
                    cls.log_info('No vSmart policy to activate')
                else:
                    cls.wait_actions(api, action_list, 'activating vSmart policy')
            except (RestAPIException, FileNotFoundError) as ex:
                cls.log_critical('Attach failed: %s', ex)


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

    @classmethod
    def runner(cls, parsed_args, api):
        cls.log_info('Starting delete%s: vManage URL: "%s"',
                     ', DRY-RUN mode' if parsed_args.dryrun else '', api.base_url)

        if parsed_args.detach:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)
                # Detach WAN Edge templates
                action_list = cls.detach_template(api, template_index, DeviceTemplateIndex.is_not_vsmart)
                if len(action_list) == 0:
                    cls.log_info('No WAN Edge attached')
                else:
                    cls.wait_actions(api, action_list, 'detaching WAN Edge templates')
                # Deactivate vSmart policy
                action_list = cls.deactivate_policy(api)
                if len(action_list) == 0:
                    cls.log_info('No vSmart policy activated')
                else:
                    cls.wait_actions(api, action_list, 'deactivating vSmart policy')
                # Detach vSmart template
                action_list = cls.detach_template(api, template_index, DeviceTemplateIndex.is_vsmart)
                if len(action_list) == 0:
                    cls.log_info('No vSmart attached')
                else:
                    cls.wait_actions(api, action_list, 'detaching vSmart template')
            except RestAPIException as ex:
                cls.log_critical('Detach failed: %s', ex)

        for tag in ordered_tags(parsed_args.tag, parsed_args.tag != CATALOG_TAG_ALL):
            cls.log_info('Inspecting %s items', tag)
            matched_item_iter = (
                (item_name, item_id, item_cls, info)
                for _, info, index, item_cls in cls.index_iter(api, catalog_iter(tag, version=api.server_version))
                for item_id, item_name in index
                if parsed_args.regex is None or regex_search(parsed_args.regex, item_name)
            )
            for item_name, item_id, item_cls, info in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    cls.log_warning('Failed retrieving %s %s', info, item_name)
                    continue
                if item.is_readonly or item.is_system:
                    cls.log_debug('Skipped %s %s %s', 'read-only' if item.is_readonly else 'system', info, item_name)
                    continue
                if parsed_args.dryrun:
                    cls.log_info('DRY-RUN: Delete %s %s', info, item_name)
                    continue

                if api.delete(item_cls.api_path.delete, item_id):
                    cls.log_info('Done: Delete %s %s', info, item_name)
                else:
                    cls.log_warning('Failed deleting %s %s', info, item_name)


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
                                    help=f'Restore source (default will be "{default_workdir(target_address)}").')

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

    @classmethod
    def runner(cls, parsed_args, api):
        if parsed_args.command == 'restore':
            start_msg = f'Restore status workdir: "{parsed_args.workdir}" -> vManage URL: "{api.base_url}"'
        else:
            start_msg = f'Set status to "{parsed_args.status}" -> vManage URL: "{api.base_url}"'
        cls.log_info('Starting certificate%s: %s', ', DRY-RUN mode' if parsed_args.dryrun else '', start_msg)

        try:
            cls.log_info('Loading WAN edge certificate list from target vManage')
            target_certs = EdgeCertificate.get_raise(api)

            matched_items = (
                (uuid, current_status, hostname, new_status)
                for uuid, current_status, hostname, new_status in parsed_args.source_iter(target_certs, parsed_args)
                if parsed_args.regex is None or regex_search(parsed_args.regex, hostname or '-', uuid)
            )
            update_list = []
            cls.log_info('Identifying items to be pushed')
            log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''
            for uuid, current_status, hostname, new_status in matched_items:
                if current_status == new_status:
                    cls.log_debug('%sSkipping %s, no changes', log_prefix, hostname or uuid)
                    continue

                cls.log_info('%sWill update %s status: %s -> %s',
                             log_prefix, hostname or uuid, current_status, new_status)
                update_list.append((uuid, new_status))

            if len(update_list) > 0:
                cls.log_info('%sPushing certificate status changes to vManage', log_prefix)
                if not parsed_args.dryrun:
                    api.post(target_certs.status_post_data(*update_list), EdgeCertificate.api_path.post)
                    action_worker = EdgeCertificateSync(api.post({}, EdgeCertificateSync.api_path.post))
                    cls.wait_actions(api, [(action_worker, None)], 'certificate sync with controllers',
                                     raise_on_failure=True)
            else:
                cls.log_info('%sNo certificate status updates to push', log_prefix)

        except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
            cls.log_critical('Failed updating WAN edge certificate status: %s', ex)


@TaskOptions.register('list')
class TaskList(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nList task:')
        task_parser.prog = f'{task_parser.prog} list'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='options', dest='option', help='Specify type of elements to list.')
        sub_tasks.required = True

        config_parser = sub_tasks.add_parser('configuration', aliases=['config'], help='List configuration items.')
        config_parser.set_defaults(table_factory=TaskList.config_table)
        config_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                   help='One or more tags for selecting groups of items. Multiple tags should be '
                                        f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                        f'"{CATALOG_TAG_ALL}" selects all items.')
        config_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                   help='Regular expression selecting items to list. Match on item names or item IDs.')

        cert_parser = sub_tasks.add_parser('certificate', aliases=['cert'], help='List certificates.')
        cert_parser.set_defaults(table_factory=TaskList.cert_table)
        cert_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression selecting devices to list. Match on hostname or '
                                      'chassis/uuid. Use "^-$" to match devices without a hostname.')

        # Parameters common to all sub-tasks
        for sub_task in (config_parser, cert_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                  help='If provided, list will read from the specified directory instead of the ' 
                                       'target vManage.')
            sub_task.add_argument('--csv', metavar='<filename>', type=filename_type,
                                  help='Instead of printing a table with list results, export as a csv file with '
                                       'the provided filename.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    @classmethod
    def runner(cls, parsed_args, api=None):
        results = parsed_args.table_factory(parsed_args, api)
        cls.log_info('List criteria matched %s items', len(results))

        if len(results) > 0:
            print_buffer = []
            print_buffer.extend(results.pretty_iter())

            if parsed_args.csv is not None:
                results.save(parsed_args.csv)
                cls.log_info('Table exported as %s', parsed_args.csv)
            else:
                print('\n'.join(print_buffer))

    @classmethod
    def config_table(cls, parsed_args, api):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        cls.log_info('Starting list configuration: %s', source_info)

        backend = api or parsed_args.workdir
        # Only perform version-based filtering if backend is api
        version = None if api is None else api.server_version

        matched_item_iter = (
            (item_name, item_id, tag, info)
            for tag, info, index, item_cls in cls.index_iter(backend, catalog_iter(*parsed_args.tags, version=version))
            for item_id, item_name in index
            if parsed_args.regex is None or regex_search(parsed_args.regex, item_name, item_id)
        )
        results = Table('Name', 'ID', 'Tag', 'Type')
        results.extend(matched_item_iter)

        return results

    @classmethod
    def cert_table(cls, parsed_args, api):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        cls.log_info('Starting list certificates: %s', source_info)

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


@TaskOptions.register('show-template')
class TaskShowTemplate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nShow template task:')
        task_parser.prog = f'{task_parser.prog} show-template'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('option', metavar='<option>', type=ShowOptions.option,
                                 help=f'Attributes to show. Available options: {ShowOptions.options()}.')
        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 help='If provided, show-template will read from the specified directory instead of '
                                      'the target vManage.')
        task_parser.add_argument('--csv', metavar='<directory>', type=filename_type,
                                 help='Instead of printing tables with the show-template results, export as csv files. '
                                      'Exported files are saved under the specified directory.')
        xor_group = task_parser.add_mutually_exclusive_group(required=True)
        xor_group.add_argument('--name', metavar='<name>', help='Device template name.')
        xor_group.add_argument('--id', metavar='<id>', type=uuid_type, help='Device template ID.')
        xor_group.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='Regular expression matching device template names.')
        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    @classmethod
    def runner(cls, parsed_args, api=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        cls.log_info('Starting show: %s', source_info)

        if parsed_args.csv is not None:
            Path(parsed_args.csv).mkdir(parents=True, exist_ok=True)

        # Dispatch to the appropriate show handler
        parsed_args.option(cls, parsed_args, api)

    @classmethod
    @ShowOptions.register('values')
    def device_template_values(cls, show_args, api):
        def item_matches(item_name, item_id):
            if show_args.id is not None:
                return item_id == show_args.id
            if show_args.name is not None:
                return item_name == show_args.name
            return regex_search(show_args.regex, item_name)

        def template_values(ext_name, template_name, template_id):
            if api is None:
                # Load from local backup
                values = DeviceTemplateValues.load(show_args.workdir, ext_name, template_name, template_id)
                if values is None:
                    cls.log_debug('Skipped %s. No template values file found.', template_name)
            else:
                # Load from vManage via API
                devices_attached = DeviceTemplateAttached.get(api, template_id)
                if devices_attached is None:
                    cls.log_error('Failed to retrieve %s attached devices', template_name)
                    return None

                try:
                    uuid_list = [uuid for uuid, _ in devices_attached]
                    values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(template_id, uuid_list),
                                                           DeviceTemplateValues.api_path.post))
                except RestAPIException:
                    cls.log_error('Failed to retrieve %s values', template_name)
                    return None

            return values

        print_buffer = []
        backend = api or show_args.workdir
        matched_item_iter = (
            (index.need_extended_name, item_name, item_id, tag, info)
            for tag, info, index, item_cls in cls.index_iter(backend, catalog_iter('template_device'))
            for item_id, item_name in index
            if item_matches(item_name, item_id) and issubclass(item_cls, DeviceTemplate)
        )
        for use_ext_name, item_name, item_id, tag, info in matched_item_iter:
            attached_values = template_values(use_ext_name, item_name, item_id)
            if attached_values is None:
                continue

            cls.log_info('Inspecting %s %s values', info, item_name)
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
                    if show_args.csv is not None:
                        filename = 'template_values_{name}_{id}.csv'.format(name=filename_safe(item_name, lower=True),
                                                                            id=csv_name or csv_id)
                        results.save(Path(show_args.csv, filename))
                    print_grp.extend(results.pretty_iter())
                print_buffer.append('\n'.join(print_grp))

        if len(print_buffer) > 0:
            if show_args.csv is not None:
                cls.log_info('Files saved under directory %s', show_args.csv)
            else:
                print('\n\n'.join(print_buffer))
        else:
            match_type = 'ID' if show_args.id is not None else 'name' if show_args.name is not None else 'regex'
            cls.log_warning('No items found with the %s provided', match_type)


@TaskOptions.register('migrate')
class TaskMigrate(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        default_output = 'migrated_{date:%Y%m%d}'.format(date=date.today())

        task_parser = argparse.ArgumentParser(description=f'{title}\nMigrate task:')
        task_parser.prog = f'{task_parser.prog} migrate'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--name', metavar='<format>', default='migrated_{name}',
                                 help='Format used to name migrated templates. Variable {name} is replaced with the '
                                      'original template name. Default is "migrated_{name}".')
        task_parser.add_argument('--from', metavar='<version>', type=version_type, dest='from_version', default='18.4',
                                 help='vManage version from source templates. Default is 18.4.')
        task_parser.add_argument('--to', metavar='<version>', type=version_type, dest='to_version', default='20.1',
                                 help='Target vManage version for template migration. Default is 20.1.')
        task_parser.add_argument('--out', metavar='<directory>', type=filename_type, dest='output',
                                 default=default_output,
                                 help=f'Destination for migrated templates (default will be "{default_output}").')
        task_parser.add_argument('--workdir', metavar='<directory>', type=existing_file_type,
                                 help='If provided, migrate will read from the specified directory instead of '
                                      'the target vManage.')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression matching the name of feature templates to be evaluated for '
                                      'migration. If not defined, all feature templates are evaluated.')
        task_parser.add_argument('--all', action='store_true',
                                 help='By default, only feature templates attached to device templates are evaluated. '
                                      'With this setting, all feature templates are evaluated.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args):
        return parsed_args.workdir is None

    @classmethod
    def runner(cls, parsed_args, api=None):
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        cls.log_info('Starting migrate: %s %s -> %s Local output dir: "%s"', source_info, parsed_args.from_version,
                     parsed_args.to_version, parsed_args.output)

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
            cls.log_info('Loaded template migration recipes')

            id_mapping = {}  # {<old_id>: <new_id>}
            for tag in ordered_tags(CATALOG_TAG_ALL, reverse=True):
                cls.log_info('Inspecting %s items', tag)

                for _, info, index_cls, item_cls in catalog_iter(tag, version=server_version):
                    item_index = cls.index_get(index_cls, backend)
                    if item_index is None:
                        cls.log_debug('Skipped %s, none found', info)
                        continue

                    name_set = {item_name for item_id, item_name in item_index}

                    is_bad_name = False
                    export_list = []
                    id_hint_map = {item_name: item_id for item_id, item_name in item_index}
                    for item_id, item_name in item_index:
                        item = cls.item_get(item_cls, backend, item_id, item_name, item_index.need_extended_name)
                        if item is None:
                            cls.log_error('Failed loading %s %s', info, item_name)
                            continue

                        try:
                            item_processor = loaded_processors.get(item_cls)
                            if item_processor is None:
                                raise StopProcessorException()

                            cls.log_debug('Evaluating %s %s', info, item_name)
                            if not item_processor.is_in_scope(item, migrate_all=parsed_args.all):
                                cls.log_debug('Skipping %s, migration not necessary', item_name)
                                raise StopProcessorException()

                            new_name = item.get_new_name(parsed_args.name)
                            if new_name is None:
                                cls.log_error('New %s name is not valid: %s', info, new_name)
                                is_bad_name = True
                                raise StopProcessorException()
                            if new_name in name_set:
                                cls.log_error('New %s name conflicts with an existing one: %s', info, new_name)
                                is_bad_name = True
                                raise StopProcessorException()

                            new_id = str(uuid4())
                            new_payload, trace_log = item_processor.eval(item, new_name, new_id)
                            for trace in trace_log:
                                cls.log_debug('Processor: %s', trace)

                            if item.is_equal(new_payload):
                                cls.log_debug('Skipping %s, no changes', item_name)
                                raise StopProcessorException()

                            new_item = item_cls(update_ids(id_mapping, new_payload))
                            id_mapping[item_id] = new_id
                            id_hint_map[new_name] = new_id

                            if item_processor.replace_original():
                                cls.log_info('Migrated %s %s as %s', info, item_name, new_name)
                                item = new_item
                            else:
                                export_list.append(new_item)

                        except StopProcessorException:
                            pass
                        finally:
                            export_list.append(item)

                    if is_bad_name:
                        raise TaskException(f'One or more new {info} names are not valid')

                    if not export_list:
                        cls.log_info('No %s migrated', info)
                        continue

                    if issubclass(item_cls, FeatureTemplate):
                        for factory_default in (factory_cedge_aaa, factory_cedge_global):
                            export_list.append(factory_default)
                            id_hint_map[factory_default.name] = factory_default.uuid
                            cls.log_debug('Added factory %s %s', info, factory_default.name)

                    new_item_index = index_cls.create(export_list, id_hint_map)
                    if new_item_index.save(parsed_args.output):
                        cls.log_info('Saved %s index', info)

                    for new_item in export_list:
                        if new_item.save(parsed_args.output, new_item_index.need_extended_name, new_item.name,
                                         id_hint_map[new_item.name]):
                            cls.log_info('Saved %s %s', info, new_item.name)

        except (ProcessorException, TaskException) as ex:
            cls.log_critical('Migration aborted: %s', ex)
