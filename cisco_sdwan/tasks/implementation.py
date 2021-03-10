"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.implementation
 This module contains the implementation of user-facing tasks
"""
__all__ = ['TaskBackup', 'TaskRestore', 'TaskDelete', 'TaskMigrate']

import argparse
from uuid import uuid4
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import RestAPIException, is_version_newer
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_base import UpdateEval, update_ids, ServerInfo
from cisco_sdwan.base.models_vmanage import (DeviceConfig, DeviceConfigRFS, DeviceTemplate, DeviceTemplateAttached,
                                             DeviceTemplateValues, DeviceTemplateIndex, FeatureTemplate, CheckVBond,
                                             PolicyVsmartIndex, EdgeInventory, ControlInventory, EdgeCertificate)
from cisco_sdwan.base.processor import StopProcessorException, ProcessorException
from cisco_sdwan.migration import factory_cedge_aaa, factory_cedge_global
from cisco_sdwan.migration.feature_migration import FeatureProcessor
from cisco_sdwan.migration.device_migration import DeviceProcessor
from .utils import (TaskOptions, TagOptions, existing_file_type, filename_type, regex_type, version_type,
                    default_workdir, ext_template_type)
from .common import regex_search, clean_dir, Task, WaitActionsException, TaskException


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
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Dry-run mode. Items to be restored are listed but not pushed to vManage.')
        task_parser.add_argument('--attach', action='store_true',
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
        check_vbond = CheckVBond.get(api)
        if check_vbond is None:
            self.log_warning('Failed retrieving vBond configuration status.')
            is_vbond_set = False
        else:
            is_vbond_set = check_vbond.is_configured

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
            if tag == 'template_device' and not is_vbond_set:
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
                                    attach_data = self.attach_template_data(
                                        api, parsed_args.workdir, index.need_extended_name,
                                        [(item.name, item_id, target_id)]
                                    )
                                else:
                                    self.log_info('Updating %s %s requires reattach of affected templates',
                                                  info, item.name)
                                    target_templates = {item_id: item_name
                                                        for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                                    templates_iter = (
                                        (target_templates[tgt_id], tgt_id)
                                        for tgt_id in put_eval.templates_affected_iter()
                                    )
                                    attach_data = self.reattach_template_data(api, templates_iter)

                                num_attach = self.attach(api, *attach_data, log_context='reattaching templates')
                                self.log_debug('Attach requests processed: %s', num_attach)
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

                # Attach WAN Edge templates
                edge_templates_iter = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart)
                )
                attach_data = self.attach_template_data(
                    api, parsed_args.workdir, saved_template_index.need_extended_name, edge_templates_iter,
                    target_uuid_set={uuid for uuid, _ in EdgeInventory.get_raise(api)}
                )
                reqs = self.attach(api, *attach_data, dryrun=parsed_args.dryrun, log_context='attaching WAN Edges')
                if reqs:
                    self.log_debug('%sAttach requests processed: %s', log_prefix, reqs)
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
                reqs = self.attach(api, *attach_data, dryrun=parsed_args.dryrun, log_context="attaching vSmarts")
                if reqs:
                    self.log_debug('%sAttach requests processed: %s', log_prefix, reqs)
                else:
                    self.log_info('No vSmart attachments needed')

                # Activate vSmart policy
                if not parsed_args.dryrun:
                    _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy
                    action_list = self.activate_policy(api, target_policies.get(policy_name), policy_name)
                    if len(action_list) == 0:
                        self.log_info('No vSmart policy to activate')
                    else:
                        self.wait_actions(api, action_list, 'activating vSmart policy', raise_on_failure=True)
            except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
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
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Dry-run mode. Items matched for removal are listed but not deleted.')
        task_parser.add_argument('--detach', action='store_true',
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
        log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''

        if parsed_args.detach:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)
                # Detach WAN Edge templates
                reqs = self.detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart),
                                   dryrun=parsed_args.dryrun, log_context='detaching WAN Edges')
                if reqs:
                    self.log_debug('%sDetach requests processed: %s', log_prefix, reqs)
                else:
                    self.log_info('No WAN Edge attached')
                # Deactivate vSmart policy
                if not parsed_args.dryrun:
                    action_list = self.deactivate_policy(api)
                    if len(action_list) == 0:
                        self.log_info('No vSmart policy activated')
                    else:
                        self.wait_actions(api, action_list, 'deactivating vSmart policy', raise_on_failure=True)
                # Detach vSmart template
                reqs = self.detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_vsmart),
                                   dryrun=parsed_args.dryrun, log_context='detaching vSmarts')
                if reqs:
                    self.log_debug('%sDetach requests processed: %s', log_prefix, reqs)
                else:
                    self.log_info('No vSmart attached')
            except (RestAPIException, WaitActionsException) as ex:
                self.log_critical('Detach failed: %s', ex)
                return

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
