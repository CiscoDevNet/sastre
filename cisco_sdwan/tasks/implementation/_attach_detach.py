import argparse
from functools import partial
from typing import Union, Optional, Callable, Tuple, Set, Mapping, Iterable
from pydantic import validator, conint
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import is_index_supported
from cisco_sdwan.base.models_vmanage import (DeviceTemplateIndex, ConfigGroupIndex, EdgeInventory, ControlInventory,
                                             PolicyVsmartIndex)
from cisco_sdwan.tasks.utils import (TaskOptions, existing_workdir_type, regex_type, default_workdir, ipv4_type,
                                     site_id_type, int_type)
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException, device_iter
from cisco_sdwan.tasks.models import TaskArgs, const
from cisco_sdwan.tasks.validators import validate_regex, validate_workdir, validate_site_id, validate_ipv4

# Default number of devices to include per attach/detach request. The value of 200 was adopted because it is what was
# validated in the lab
DEFAULT_BATCH_SIZE = 200


def build_device_maps(selected_devices_iter: Iterable[Tuple[str, str]],
                      template_ops_uuid_set: Set[str],
                      cfg_group_ops_uuid_set: Set[str]) -> Tuple[Mapping[str, str], Mapping[str, str]]:
    selected_devices = [(uuid, name) for uuid, name in selected_devices_iter]
    return (
        {uuid: name for uuid, name in selected_devices if uuid in template_ops_uuid_set},
        {uuid: name for uuid, name in selected_devices if uuid in cfg_group_ops_uuid_set}
    )


@TaskOptions.register('attach')
class TaskAttach(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nAttach task:')
        task_parser.prog = f'{task_parser.prog} attach'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='attach options')
        sub_tasks.required = True

        edge_parser = sub_tasks.add_parser('edge', help='attach/deploy WAN edges')
        edge_parser.set_defaults(template_filter=DeviceTemplateIndex.is_not_vsmart,
                                 device_sets=TaskAttach.edge_sets,
                                 set_title="WAN Edge")

        vsmart_parser = sub_tasks.add_parser('vsmart', help='attach/deploy vSmarts')
        vsmart_parser.set_defaults(template_filter=DeviceTemplateIndex.is_vsmart,
                                   device_sets=TaskAttach.vsmart_sets,
                                   set_title="vSmart")
        vsmart_parser.add_argument('--activate', action='store_true',
                                   help='activate centralized policy after vSmart template attach/deploy')

        # Parameters common to all sub-tasks
        for sub_task in (edge_parser, vsmart_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                  default=default_workdir(target_address), help='attach source (default: %(default)s)')
            sub_task.add_argument('--templates', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting templates to attach. Match on template name.')
            sub_task.add_argument('--config-groups', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting config-groups to deploy. '
                                       'Match on config-group name.')
            sub_task.add_argument('--devices', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting devices to attach/deploy. Match on device name.')
            sub_task.add_argument('--reachable', action='store_true', help='select reachable devices only')
            sub_task.add_argument('--site', metavar='<id>', type=site_id_type, help='select devices with site ID')
            sub_task.add_argument('--system-ip', metavar='<ipv4>', type=ipv4_type, help='select device with system IP')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. Attach operations are listed but not is pushed to vManage.')
            sub_task.add_argument('--batch', metavar='<size>', type=partial(int_type, 1, 9999),
                                  default=DEFAULT_BATCH_SIZE,
                                  help='maximum number of devices to include per vManage attach request '
                                       '(default: %(default)s)')

        return task_parser.parse_args(task_args)

    @staticmethod
    def edge_sets(api: Rest) -> Tuple[Set[str], Set[str]]:
        inventory = EdgeInventory.get_raise(api)
        attach_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_available)
        }
        deploy_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_available, EdgeInventory.is_cedge)
        }
        return attach_set, deploy_set

    @staticmethod
    def vsmart_sets(api: Rest) -> Tuple[Set[str], Set[str]]:
        inventory = ControlInventory.get_raise(api)
        attach_set = {
            entry.uuid for entry in inventory.filtered_iter(ControlInventory.is_available, ControlInventory.is_vsmart)
        }
        deploy_set = set()
        return attach_set, deploy_set

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.is_dryrun = parsed_args.dryrun
        self.log_info(f'Attach task: Local workdir: "{parsed_args.workdir}" -> vManage URL: "{api.base_url}"')

        attach_map, deploy_map = build_device_maps(
            device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site, parsed_args.system_ip,
                        default=None),
            *parsed_args.device_sets(api)
        )

        # Config-group deployments
        deploy_reqs = 0
        if deploy_map:
            try:
                saved_groups_index = ConfigGroupIndex.load(parsed_args.workdir)
                if saved_groups_index is None:
                    self.log_debug("Will skip deploy, no local config-group index")
                    raise StopIteration()

                if not is_index_supported(ConfigGroupIndex, version=api.server_version):
                    self.log_warning("Will skip deploy, target vManage does not support config-groups")
                    raise StopIteration()

                target_cfg_groups = {item_name: item_id for item_id, item_name in ConfigGroupIndex.get_raise(api)}
                selected_cfg_groups = (
                    (saved_name, saved_id, target_cfg_groups.get(saved_name))
                    for saved_id, saved_name in saved_groups_index
                    if parsed_args.config_groups is None or regex_search(parsed_args.config_groups, saved_name)
                )
                deploy_data = self.cfg_group_deploy_data(api, parsed_args.workdir,
                                                         saved_groups_index.need_extended_name, selected_cfg_groups,
                                                         deploy_map)
                deploy_reqs = self.cfg_group_deploy(api, deploy_data, deploy_map, chunk_size=parsed_args.batch,
                                                    log_context=f"config-group deploying {parsed_args.set_title}")
                if deploy_reqs:
                    self.log_debug(f'Deploy requests processed: {deploy_reqs}')
            except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                self.log_error(f'Failed: Config-group deployments: {ex}')
            except StopIteration:
                pass

        if not deploy_reqs:
            self.log_info(f'No {parsed_args.set_title} config-group deployments to process')

        # Template attachments
        attach_reqs = 0
        if attach_map:
            try:
                saved_template_index = DeviceTemplateIndex.load(parsed_args.workdir)
                if saved_template_index is None:
                    self.log_debug("Will skip attach, no local device template index")
                    raise StopIteration()

                target_templates = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
                selected_templates = (
                    (saved_name, saved_id, target_templates.get(saved_name))
                    for saved_id, saved_name in saved_template_index.filtered_iter(parsed_args.template_filter,
                                                                                   DeviceTemplateIndex.is_attached)
                    if parsed_args.templates is None or regex_search(parsed_args.templates, saved_name)
                )
                attach_data = self.template_attach_data(api, parsed_args.workdir,
                                                        saved_template_index.need_extended_name, selected_templates,
                                                        target_uuid_set=set(attach_map))
                attach_reqs = self.template_attach(api, *attach_data, chunk_size=parsed_args.batch,
                                                   log_context=f"template attaching {parsed_args.set_title}")
                if attach_reqs:
                    self.log_debug(f"Attach requests processed: {attach_reqs}")
            except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                self.log_error(f"Failed: Template attachments: {ex}")
            except StopIteration:
                pass

        if not attach_reqs:
            self.log_info(f"No {parsed_args.set_title} template attachments to process")

        # vSmart policy activate
        if parsed_args.device_sets is TaskAttach.vsmart_sets and parsed_args.activate:
            activate_reqs = 0
            try:
                _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy
                target_policies = {item_name: item_id for item_id, item_name in PolicyVsmartIndex.get_raise(api)}
                activate_reqs = self.policy_activate(api, target_policies.get(policy_name), policy_name,
                                                     log_context="activating vSmart policy")
                if activate_reqs:
                    self.log_debug(f'Activate requests processed: {activate_reqs}')
            except (RestAPIException, WaitActionsException) as ex:
                self.log_error(f"Failed: vSmart policy activate: {ex}")
            except FileNotFoundError:
                self.log_debug("Will skip vSmart policy activate, no local vSmart policy index")

            if not activate_reqs:
                self.log_info('No vSmart policy activate to process')

        return


@TaskOptions.register('detach')
class TaskDetach(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nDetach task:')
        task_parser.prog = f'{task_parser.prog} detach'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='detach options')
        sub_tasks.required = True

        edge_parser = sub_tasks.add_parser('edge', help='detach/dissociate WAN edges')
        edge_parser.set_defaults(template_filter=DeviceTemplateIndex.is_not_vsmart,
                                 device_sets=TaskDetach.edge_sets,
                                 set_title="WAN Edge")

        vsmart_parser = sub_tasks.add_parser('vsmart', help='detach/dissociate vSmarts')
        vsmart_parser.set_defaults(template_filter=DeviceTemplateIndex.is_vsmart,
                                   device_sets=TaskDetach.vsmart_sets,
                                   set_title="vSmart")

        # Parameters common to all sub-tasks
        for sub_task in (edge_parser, vsmart_parser):
            sub_task.add_argument('--templates', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting templates to detach. Match on template name.')
            sub_task.add_argument('--config-groups', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting config-groups to dissociate. '
                                       'Match on config-group name.')
            sub_task.add_argument('--devices', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting devices to detach/dissociate. '
                                       'Match on device name.')
            sub_task.add_argument('--reachable', action='store_true', help='select reachable devices only')
            sub_task.add_argument('--site', metavar='<id>', type=site_id_type, help='select devices with site ID')
            sub_task.add_argument('--system-ip', metavar='<ipv4>', type=ipv4_type, help='select device with system IP')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. Attach operations are listed but nothing is pushed to vManage.')
            sub_task.add_argument('--batch', metavar='<size>', type=partial(int_type, 1, 9999),
                                  default=DEFAULT_BATCH_SIZE,
                                  help='maximum number of devices to include per vManage detach request '
                                       '(default: %(default)s)')

        return task_parser.parse_args(task_args)

    @staticmethod
    def edge_sets(api: Rest) -> Tuple[Set[str], Set[str]]:
        inventory = EdgeInventory.get_raise(api)
        attached_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_attached)
        }
        associated_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_associated)
        }
        return attached_set, associated_set

    @staticmethod
    def vsmart_sets(api: Rest) -> Tuple[Set[str], Set[str]]:
        inventory = ControlInventory.get_raise(api)
        attached_set = {
            entry.uuid for entry in inventory.filtered_iter(ControlInventory.is_attached, ControlInventory.is_vsmart)
        }
        associated_set = set()
        return attached_set, associated_set

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.is_dryrun = parsed_args.dryrun
        self.log_info(f'Detach templates task: vManage URL: "{api.base_url}"')

        attached_map, associated_map = build_device_maps(
            device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site, parsed_args.system_ip,
                        default=None),
            *parsed_args.device_sets(api)
        )

        # Template detachments
        detach_reqs = 0
        if attached_map:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)
                selected_templates = [
                    (t_id, t_name) for t_id, t_name in template_index.filtered_iter(parsed_args.template_filter,
                                                                                    DeviceTemplateIndex.is_attached)
                    if parsed_args.templates is None or regex_search(parsed_args.templates, t_name)
                ]
                # vSmart policy deactivate
                if parsed_args.device_sets is TaskDetach.vsmart_sets and selected_templates:
                    deactivate_reqs = self.policy_deactivate(api, log_context='deactivating vSmart policy')
                    if deactivate_reqs:
                        self.log_debug(f'Deactivate requests processed: {deactivate_reqs}')
                    else:
                        self.log_info('No vSmart policy deactivate needed')
                # Detach templates
                detach_reqs = self.template_detach(api, selected_templates, attached_map,
                                                   chunk_size=parsed_args.batch,
                                                   log_context=f"template detaching {parsed_args.set_title}")
                if detach_reqs:
                    self.log_debug(f'Detach requests processed: {detach_reqs}')
            except (RestAPIException, WaitActionsException) as ex:
                self.log_error(f'Failed: Template detachments: {ex}')

        if not detach_reqs:
            self.log_info(f'No {parsed_args.set_title} template detachments to process')

        # Config-group dissociates and automated rule deletes
        diss_reqs, rule_reqs = 0, 0
        if associated_map:
            try:
                selected_cfg_groups = [
                    (cfg_group_id, cfg_group_name) for cfg_group_id, cfg_group_name in ConfigGroupIndex.get_raise(api)
                    if parsed_args.config_groups is None or regex_search(parsed_args.config_groups, cfg_group_name)
                ]
                diss_reqs = self.cfg_group_dissociate(api, selected_cfg_groups, associated_map,
                                                      chunk_size=parsed_args.batch,
                                                      log_context=f"config-group dissociating {parsed_args.set_title}")
                if diss_reqs:
                    self.log_debug(f'Dissociate requests processed: {diss_reqs}')

                rule_reqs = self.cfg_group_rules_delete(api, selected_cfg_groups)
                if rule_reqs:
                    self.log_debug(f'Automated rule delete requests processed: {rule_reqs}')
            except (RestAPIException, WaitActionsException) as ex:
                self.log_error(f'Failed: Config-group dissociate: {ex}')

        if not (diss_reqs + rule_reqs):
            self.log_info(f'No {parsed_args.set_title} config-group dissociate or automated rule deletes to process')

        return


class AttachDetachArgs(TaskArgs):
    templates: Optional[str] = None
    config_groups: Optional[str] = None
    devices: Optional[str] = None
    site: Optional[str] = None
    system_ip: Optional[str] = None
    reachable: bool = False
    dryrun: bool = False
    batch: conint(ge=1, lt=9999) = DEFAULT_BATCH_SIZE

    # Validators
    _validate_regex = validator('templates', 'config_groups', 'devices', allow_reuse=True)(validate_regex)
    _validate_site_id = validator('site', allow_reuse=True)(validate_site_id)
    _validate_ipv4 = validator('system_ip', allow_reuse=True)(validate_ipv4)


class AttachVsmartArgs(AttachDetachArgs):
    workdir: str
    activate: bool = False
    template_filter: Callable = const(DeviceTemplateIndex.is_vsmart)
    device_sets: Callable = const(TaskAttach.vsmart_sets)
    set_title: str = const('vSmart')

    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)


class AttachEdgeArgs(AttachDetachArgs):
    workdir: str
    template_filter: Callable = const(DeviceTemplateIndex.is_not_vsmart)
    device_sets: Callable = const(TaskAttach.edge_sets)
    set_title: str = const('WAN Edge')

    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)


class DetachVsmartArgs(AttachDetachArgs):
    template_filter: Callable = const(DeviceTemplateIndex.is_vsmart)
    device_sets: Callable = const(TaskDetach.vsmart_sets)
    set_title: str = const('vSmart')


class DetachEdgeArgs(AttachDetachArgs):
    template_filter: Callable = const(DeviceTemplateIndex.is_not_vsmart)
    device_sets: Callable = const(TaskDetach.edge_sets)
    set_title: str = const('WAN Edge')
