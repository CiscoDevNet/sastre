import argparse
from typing import Union, Optional
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL
from cisco_sdwan.base.models_base import ServerInfo
from cisco_sdwan.base.models_vmanage import (DeviceConfig, DeviceConfigRFS, DeviceTemplate, DeviceTemplateAttached,
                                             DeviceTemplateValues, EdgeInventory, ControlInventory, EdgeCertificate)
from cisco_sdwan.tasks.utils import TaskOptions, TagOptions, filename_type, regex_type, default_workdir
from cisco_sdwan.tasks.common import regex_search, clean_dir, Task


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nBackup task:')
        task_parser.prog = f'{task_parser.prog} backup'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('--workdir', metavar='<directory>', type=filename_type,
                                 default=default_workdir(target_address),
                                 help='backup destination (default: %(default)s)')
        task_parser.add_argument('--no-rollover', action='store_true',
                                 help='by default, if workdir already exists (before a new backup is saved) the old '
                                      'workdir is renamed using a rolling naming scheme. This option disables this '
                                      'automatic rollover.')
        task_parser.add_argument('--save-running', action='store_true',
                                 help='include the running config from each node to the backup. This is useful for '
                                      'reference or documentation purposes. It is not needed by the restore task.')
        mutex = task_parser.add_mutually_exclusive_group()
        mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names to backup, within selected tags.')
        mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names NOT to backup, within selected tags.')
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='one or more tags for selecting items to be backed up. Multiple tags should be '
                                      f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                      f'"{CATALOG_TAG_ALL}" selects all items, including WAN edge certificates and '
                                      'device configurations.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info('Starting backup: vManage URL: "%s" -> Local workdir: "%s"', api.base_url, parsed_args.workdir)

        # Backup workdir must be empty for a new backup
        saved_workdir = clean_dir(parsed_args.workdir, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_workdir:
            self.log_info('Previous backup under "%s" was saved as "%s"', parsed_args.workdir, saved_workdir)

        target_info = ServerInfo(server_version=api.server_version)
        if target_info.save(parsed_args.workdir):
            self.log_info('Saved vManage server information')

        if parsed_args.save_running:
            self.save_running_configs(api, parsed_args.workdir)

        # Backup items not registered to the catalog, but to be included when tag is 'all'
        if CATALOG_TAG_ALL in parsed_args.tags:
            edge_certs = EdgeCertificate.get(api)
            if edge_certs is None:
                self.log_error('Failed backup WAN edge certificates')
            elif edge_certs.save(parsed_args.workdir):
                self.log_info('Saved WAN edge certificates')

        # Backup items registered to the catalog
        for _, info, index_cls, item_cls in catalog_iter(*parsed_args.tags, version=api.server_version):
            item_index = index_cls.get(api)
            if item_index is None:
                self.log_debug('Skipped %s, item not supported by this vManage', info)
                continue
            if item_index.save(parsed_args.workdir):
                self.log_info('Saved %s index', info)

            regex = parsed_args.regex or parsed_args.not_regex
            matched_item_iter = (
                (item_id, item_name) for item_id, item_name in item_index
                if regex is None or regex_search(regex, item_name, inverse=parsed_args.regex is None)
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

        return

    def save_running_configs(self, api: Optional[Rest], workdir: str) -> None:
        inventory_list = [(ControlInventory.get(api), 'controller')]
        if not api.is_provider or api.is_tenant_scope:
            inventory_list.append((EdgeInventory.get(api), 'WAN edge'))

        for inventory, info in inventory_list:
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
                    if item.save(workdir, item_name=hostname, item_id=uuid):
                        self.log_info('Done %s device configuration %s', config_type, hostname)
