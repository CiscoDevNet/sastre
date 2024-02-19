import argparse
from typing import Union, Optional, List, Dict, Any
from pydantic import validator, root_validator
from uuid import uuid4
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL
from cisco_sdwan.base.models_base import ServerInfo
from cisco_sdwan.base.models_vmanage import (DeviceConfig, DeviceConfigRFS, DeviceTemplate, DeviceTemplateAttached,
                                             DeviceTemplateValues, EdgeInventory, ControlInventory, EdgeCertificate,
                                             ConfigGroup, ConfigGroupValues, ConfigGroupAssociated, ConfigGroupRules)
from cisco_sdwan.tasks.utils import TaskOptions, TagOptions, filename_type, regex_type, default_workdir
from cisco_sdwan.tasks.common import regex_search, clean_dir, Task, archive_create
from cisco_sdwan.tasks.models import TaskArgs, validate_catalog_tag
from cisco_sdwan.tasks.validators import validate_regex, validate_filename


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nBackup task:')
        task_parser.prog = f'{task_parser.prog} backup'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        mutex_dest = task_parser.add_mutually_exclusive_group()
        mutex_dest.add_argument('--archive', metavar='<filename>', type=filename_type,
                                help='backup to zip archive')
        mutex_dest.add_argument('--workdir', metavar='<directory>', type=filename_type,
                                default=default_workdir(target_address),
                                help='backup to directory (default: %(default)s)')
        task_parser.add_argument('--no-rollover', action='store_true',
                                 help='by default, if workdir already exists (before a new backup is saved) the old '
                                      'workdir is renamed using a rolling naming scheme. This option disables this '
                                      'automatic rollover.')
        task_parser.add_argument('--save-running', action='store_true',
                                 help='include the running config from each node to the backup. This is useful for '
                                      'reference or documentation purposes. It is not needed by the restore task.')
        mutex_regex = task_parser.add_mutually_exclusive_group()
        mutex_regex.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='regular expression matching item names to backup, within selected tags.')
        mutex_regex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                                 help='regular expression matching item names NOT to backup, within selected tags.')
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='one or more tags for selecting items to be backed up. Multiple tags should be '
                                      f'separated by space. Available tags: {TagOptions.options()}. Special tag '
                                      f'"{CATALOG_TAG_ALL}" selects all items, including WAN edge certificates and '
                                      'device configurations.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        if parsed_args.archive:
            self.log_info(f'Backup task: vManage URL: "{api.base_url}" -> Local archive file: "{parsed_args.archive}"')
            parsed_args.workdir = str(uuid4())
            self.log_debug(f'Temporary workdir: {parsed_args.workdir}')
        else:
            self.log_info(f'Backup task: vManage URL: "{api.base_url}" -> Local workdir: "{parsed_args.workdir}"')

        # Backup workdir must be empty for a new backup
        saved_workdir = clean_dir(parsed_args.workdir, max_saved=0 if parsed_args.no_rollover else 99)
        if saved_workdir:
            self.log_info(f'Previous backup under "{parsed_args.workdir}" was saved as "{saved_workdir}"')

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
                self.log_debug(f'Skipped {info}, item not supported by this vManage')
                continue
            if item_index.save(parsed_args.workdir):
                self.log_info(f'Saved {info} index')

            regex = parsed_args.regex or parsed_args.not_regex
            matched_item_iter = (
                (item_id, item_name) for item_id, item_name in item_index
                if regex is None or regex_search(regex, item_name, inverse=parsed_args.regex is None)
            )
            for item_id, item_name in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    self.log_error(f'Failed backup {info} {item_name}')
                    continue
                if item.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                    self.log_info(f'Done {info} {item_name}')

                # Special case for DeviceTemplate, handle DeviceTemplateAttached and DeviceTemplateValues
                if isinstance(item, DeviceTemplate):
                    devices_attached = DeviceTemplateAttached.get(api, item_id)
                    if devices_attached is None:
                        self.log_error(f'Failed backup {info} {item_name} attached devices')
                        continue
                    if devices_attached.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                        self.log_info(f'Done {info} {item_name} attached devices')
                    else:
                        self.log_debug(f'Skipped {info} {item_name} attached devices, none found')
                        continue

                    try:
                        uuid_list = [uuid for uuid, _ in devices_attached]
                        values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(item_id, uuid_list),
                                                               DeviceTemplateValues.api_path.post))
                        if values.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                            self.log_info(f'Done {info} {item_name} values')
                    except RestAPIException as ex:
                        self.log_error(f'Failed backup {info} {item_name} values: {ex}')

                # Special case for ConfigGroup, handle ConfigGroupAssociated, ConfigGroupValues, ConfigGroupRules
                if isinstance(item, ConfigGroup) and item.devices_associated:
                    for sub_item_info, sub_item_cls in (('associated devices', ConfigGroupAssociated),
                                                        ('automated rules', ConfigGroupRules),
                                                        ('values', ConfigGroupValues)):
                        sub_item = sub_item_cls.get(api, configGroupId=item_id)
                        if sub_item is None:
                            self.log_error(f'Failed backup {info} {item_name} {sub_item_info}')
                            continue
                        if sub_item.save(parsed_args.workdir, item_index.need_extended_name, item_name, item_id):
                            self.log_info(f'Done {info} {item_name} {sub_item_info}')

        if parsed_args.archive:
            archive_create(parsed_args.archive, parsed_args.workdir)
            self.log_info(f'Created archive file "{parsed_args.archive}"')
            clean_dir(parsed_args.workdir, max_saved=0)
            self.log_debug('Temporary workdir deleted')

        return

    def save_running_configs(self, api: Optional[Rest], workdir: str) -> None:
        inventory_list = [(ControlInventory.get(api), 'controller')]
        if not api.is_provider or api.is_tenant_scope:
            inventory_list.append((EdgeInventory.get(api), 'WAN edge'))

        for inventory, info in inventory_list:
            if inventory is None:
                self.log_error(f'Failed retrieving {info} inventory')
                continue

            for uuid, _, hostname, _ in inventory.extended_iter():
                if hostname is None:
                    self.log_debug(f'Skipping {uuid}, no hostname')
                    continue

                for item, config_type in ((DeviceConfig.get(api, DeviceConfig.api_params(uuid)), 'CFS'),
                                          (DeviceConfigRFS.get(api, DeviceConfigRFS.api_params(uuid)), 'RFS')):
                    if item is None:
                        self.log_error(f'Failed backup {config_type} device configuration {hostname}')
                        continue
                    if item.save(workdir, item_name=hostname, item_id=uuid):
                        self.log_info(f'Done {config_type} device configuration {hostname}')


class BackupArgs(TaskArgs):
    archive: Optional[str] = None
    workdir: Optional[str] = None
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    no_rollover: bool = False
    save_running: bool = False
    tags: List[str]

    # Validators
    _validate_filename = validator('workdir', 'archive', allow_reuse=True)(validate_filename)
    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_tags = validator('tags', each_item=True, allow_reuse=True)(validate_catalog_tag)

    @root_validator(skip_on_failure=True)
    def mutex_validations(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if bool(values.get('archive')) == bool(values.get('workdir')):
            raise ValueError('Either "archive" or "workdir" must to be provided')

        if values.get('regex') is not None and values.get('not_regex') is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return values
