import argparse
from functools import partial
from typing import Union, Optional, List, Dict, Tuple, Set, Sequence
from collections.abc import Mapping, Callable, Iterable

import yaml
from pydantic import Field, field_validator, BaseModel, validator, ValidationError
from typing_extensions import Annotated
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import is_index_supported
from cisco_sdwan.base.models_vmanage import (DeviceTemplateIndex, ConfigGroupIndex, EdgeInventory, ControlInventory,
                                             PolicyVsmartIndex, Device, ConfigGroupRules, ConfigGroupAssociated,
                                             ConfigGroupValues)
from cisco_sdwan.tasks.utils import (TaskOptions, existing_workdir_type, regex_type, default_workdir, ipv4_type,
                                     site_id_type, int_type, filename_type, existing_file_type)
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException, device_iter, TaskException
from cisco_sdwan.tasks.models import TaskArgs, const
from cisco_sdwan.tasks.validators import validate_regex, validate_workdir, validate_site_id, validate_ipv4

# Default number of devices to include per attach/detach request. The value of 200 was adopted because it is what was
# validated in the lab
DEFAULT_BATCH_SIZE = 200


def build_device_maps(selected_devices_iter: Iterable[tuple[str, str]],
                      template_ops_uuid_set: set[str],
                      cfg_group_ops_uuid_set: set[str]) -> tuple[Mapping[str, str], Mapping[str, str]]:
    selected_devices = [(uuid, name) for uuid, name in selected_devices_iter]
    return (
        {uuid: name for uuid, name in selected_devices if uuid in template_ops_uuid_set},
        {uuid: name for uuid, name in selected_devices if uuid in cfg_group_ops_uuid_set}
    )


class DeviceAttachTemplateModel(BaseModel):
    templateName: str
    isCliTemplate: bool
    device: List[Dict[str, str]]

    @classmethod
    def replace_empty_with_default(cls, value):
        return {k: '{PLACEHOLDER}' if v == '' or v is None else v for k, v in value.items()}

    @validator('device', pre=True)
    def validate_device(cls, value):
        return [cls.replace_empty_with_default(data) for data in value]


class AttachTemplatesModel(BaseModel):
    edge_templates: Optional[List[DeviceAttachTemplateModel]] = None
    vsmart_templates: Optional[List[DeviceAttachTemplateModel]] = None

    def get_vsmart_templates(self) -> List[DeviceAttachTemplateModel]:
        return self.vsmart_templates

    def get_edge_templates(self) -> List[DeviceAttachTemplateModel]:
        return self.edge_templates

    def get_templates(self, func: Callable):
        return func(self)


class VsmartPolicyModel(BaseModel):
    name: Union[str, None] = None
    activate: bool = False


class TagRulesModel(BaseModel):
    deviceAttribute: str
    rule: str
    values: List[str]
    tagId: Optional[str]

    @validator('rule')
    def validate_rule(cls, v):
        rule_options = ('equal', 'notEqual', 'contain', 'notContain')
        if v not in rule_options:
            raise ValueError(f'"{v}" is not a valid rule. Options are: {", ".join(rule_options)}.')
        return v


class NameValueModel(BaseModel):
    name: str
    value: Optional[str] = '{PLACEHOLDER}'
    suggestions: Optional[List[str]]


class DeviceVariablesModel(BaseModel):
    deviceName: str
    variables: Optional[List[NameValueModel]]


class DeviceAssociationValuesModel(BaseModel):
    family: Optional[str]
    devices: List[DeviceVariablesModel]


class ConfigGroupsModel(BaseModel):
    configGroupName: str
    tag_rules: Optional[TagRulesModel]
    devices_association_values: Optional[DeviceAssociationValuesModel]


class AttachModel(BaseModel):
    attach_templates: Optional[AttachTemplatesModel]
    config_groups: Optional[List[ConfigGroupsModel]]
    vsmart_policy: Optional[VsmartPolicyModel]


def device_maps(selected_devices_iter: Iterable[Tuple[str, str]],
                vsmart_uuid_set: Tuple[Set[str], Set[str]],
                cedge_uuid_set: Tuple[Set[str], Set[str]],
                vedge_uuid_set: Tuple[Set[str], Set[str]]) -> Tuple[Mapping[str, str], Mapping[str, str], Mapping[str, str],
                                                                    Mapping[str, str], Mapping[str, str], Mapping[str, str]]:
    selected_devices = dict(selected_devices_iter)
    selected_devices_keys = selected_devices.keys()
    return ({uuid: selected_devices[uuid] for uuid in selected_devices_keys & vsmart_uuid_set[0]},
            {uuid: selected_devices[uuid] for uuid in selected_devices_keys & vsmart_uuid_set[1]},
            {uuid: selected_devices[uuid] for uuid in selected_devices_keys & cedge_uuid_set[0]},
            {uuid: selected_devices[uuid] for uuid in selected_devices_keys & cedge_uuid_set[1]},
            {uuid: selected_devices[uuid] for uuid in selected_devices_keys & vedge_uuid_set[0]},
            {uuid: selected_devices[uuid] for uuid in selected_devices_keys & vedge_uuid_set[1]})


def load_attach_data(template_file: str) -> AttachModel:
    def load_yaml(filename):
        try:
            with open(filename) as yaml_file:
                return yaml.safe_load(yaml_file)
        except FileNotFoundError as ex:
            raise FileNotFoundError(f'Could not load attach file: {ex}') from None
        except yaml.YAMLError as ex:
            raise TaskException(f'Attach YAML syntax error: {ex}') from None

    attach_file_dict = load_yaml(template_file)
    attach_model = None
    try:
        attach_model = AttachModel(**attach_file_dict)
    except ValidationError as e:
        raise TaskException(f'Invalid attach file: {e}') from None
    return attach_model


def build_template_attach_data(api: Rest, templates: List[DeviceAttachTemplateModel], title: str) -> Tuple[list, bool]:
    def raise_value_error(msg):
        raise ValueError(msg)

    if templates is None:
        raise ValueError(f"no {title} templates found in YML template file") from None
    template_name_id = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
    attach_data = [(template.templateName, template_name_id.get(template.templateName)
    if template_name_id.get(template.templateName) is not None
    else raise_value_error(f"template Id for {template.templateName} not found!"),
                    template.device, template.isCliTemplate)
                   for _, template in enumerate(templates)
                   ]
    return attach_data, False


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
                                 subtask_handler=TaskAttach.attach,
                                 device_sets=TaskAttach.edge_sets,
                                 set_title="WAN Edge")

        vsmart_parser = sub_tasks.add_parser('vsmart', help='attach/deploy vSmarts')
        vsmart_parser.set_defaults(template_filter=DeviceTemplateIndex.is_vsmart,
                                   subtask_handler=TaskAttach.attach,
                                   device_sets=TaskAttach.vsmart_sets,
                                   set_title="vSmart")
        vsmart_parser.add_argument('--activate', action='store_true',
                                   help='activate centralized policy after vSmart template attach/deploy')

        attach_create_parser = sub_tasks.add_parser('create',
                                                    help='attach create templates and config-groups to YAML file')
        attach_create_parser.set_defaults(subtask_handler=TaskAttach.attach_create,
                                          set_title="create vSmart and/or WAN Edge attach data")
        attach_create_parser.add_argument('--device-types', choices=['vsmart', 'edge', 'all'],
                                          default='all', help='device types')
        attach_create_parser.add_argument('--save-attach-file', metavar='<filename>', type=filename_type,
                                          help='save attach file as yaml file')

        for sub_task in (edge_parser, vsmart_parser):
            mutex_regex = sub_task.add_mutually_exclusive_group()
            mutex_regex.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                     default=default_workdir(target_address),
                                     help='attach source (default: %(default)s)')
            mutex_regex.add_argument('--attach-file', metavar='<filename>', type=existing_file_type,
                                     help='load device templates attach and vsmart policy activate from attach YAML file')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. Attach operations are listed but not is pushed to vManage.')
            sub_task.add_argument('--batch', metavar='<size>', type=partial(int_type, 1, 9999),
                                  default=DEFAULT_BATCH_SIZE,
                                  help='maximum number of devices to include per vManage attach request '
                                       '(default: %(default)s)')

        # Parameters common to all sub-tasks
        for sub_task in (edge_parser, vsmart_parser, attach_create_parser):
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


        return task_parser.parse_args(task_args)

    @staticmethod
    def edge_sets(api: Rest) -> tuple[set[str], set[str]]:
        inventory = EdgeInventory.get_raise(api)
        attach_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_available)
        }
        deploy_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_available, EdgeInventory.is_cedge)
        }
        return attach_set, deploy_set

    @staticmethod
    def vsmart_sets(api: Rest) -> tuple[set[str], set[str]]:
        inventory = ControlInventory.get_raise(api)
        attach_set = {
            entry.uuid for entry in inventory.filtered_iter(ControlInventory.is_available, ControlInventory.is_vsmart)
        }
        deploy_set = set()
        return attach_set, deploy_set

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        return parsed_args.subtask_handler(self, parsed_args, api)

    def attach(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.is_dryrun = parsed_args.dryrun
        source_info = f'Local workdir: "{parsed_args.workdir}"' if parsed_args.attach_file is None else f'Attach file: "{parsed_args.attach_file}"'
        self.log_info(f'Attach task source: {source_info} -> vManage URL: "{api.base_url}"')

        attach_map, deploy_map = None, None
        attach_model = None
        attach_data = None
        deploy_data = None
        if parsed_args.attach_file:
            try:
                attach_model = load_attach_data(parsed_args.attach_file)
            except (FileNotFoundError, TaskException) as ex:
                self.log_error(f"Failed: Loading attach file: {ex}")
                return

            if attach_model:
                # Config-group deployments
                if attach_model.config_groups and parsed_args.device_sets is TaskAttach.edge_sets:
                    try:
                        cfg_group_name_id = {item_name: item_id for item_id, item_name in ConfigGroupIndex.get_raise(api)}
                        device_name_id = {item_name: item_id for item_id, item_name in Device.get_raise(api)}
                        deploy_data = self.config_group_device_association(api, attach_model.config_groups, cfg_group_name_id,
                                                                           device_name_id, parsed_args.set_title)
                        deploy_map = {}
                    except (RestAPIException, ValueError) as ex:
                        self.log_error(f"Failed: config group deployments data: {ex}")

                # Template attachments
                if attach_model.attach_templates:
                    try:
                        templates = attach_model.attach_templates.get_templates(parsed_args.device_type)
                        attach_data = build_template_attach_data(api, templates, parsed_args.set_title)
                    except (RestAPIException, ValueError) as ex:
                        self.log_error(f"Failed: template attachments data: {ex}")
        else:  # load from workdir
            attach_map, deploy_map = build_device_maps(
                device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site, parsed_args.system_ip,
                            default=None),
                *parsed_args.device_sets(api)
            )
            # Config-group deployments
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
                    deploy_data = self.cfg_group_deploy_data(api, parsed_args.workdir, saved_groups_index.need_extended_name,
                                                             selected_cfg_groups, deploy_map)
                except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                    self.log_error(f'Failed: loading Config-group deployments: {ex}')
                except StopIteration:
                    pass

            # Template attachments
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
                except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
                    self.log_error(f"Failed: loading Template attachments: {ex}")
                except StopIteration:
                    pass

        # Config-group deployments
        deploy_reqs = 0
        if deploy_data:
            try:
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
        if attach_data:
            try:
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
        if parsed_args.device_sets is TaskAttach.vsmart_sets:
            activate_reqs = 0
            policy_name = None
            try:
                if parsed_args.attach_file:
                    vsmart_policy = attach_model.vsmart_policy
                    if vsmart_policy is not None and vsmart_policy.activate and vsmart_policy.name is not None:
                        policy_name = vsmart_policy.name if self.is_policy_name_valid(api, vsmart_policy.name) else None
                    else:
                        self.log_info('No vsmart policy to activate from attach file')
                elif parsed_args.activate:
                    _, policy_name = PolicyVsmartIndex.load(parsed_args.workdir, raise_not_found=True).active_policy

                if policy_name:
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

    def config_group_device_association(self, api: Rest, config_groups: List[ConfigGroupsModel],
                                        cfg_group_name_id: Dict[str, str],
                                        device_name_id: Dict[str, str], title: str) -> Sequence[
        Tuple[str, str, Sequence]]:
        def raise_value_error(msg):
            raise ValueError(msg)

        def associate_tags(tag_rules: TagRulesModel, cfg_grp_Id: str):
            payload = {
                "data": [{
                    "configGroupId": cfg_grp_Id,
                    "deviceAttribute": tag_rules.deviceAttribute,
                    "rule": tag_rules.rule,
                    "values": tag_rules.values
                }]
            }
            if tag_rules.tagId:
                payload["data"][0]["tagId"] = tag_rules.tagId
                ConfigGroupRules(payload).put_raise(api, config_group_id=cfg_grp_Id)
            else:
                ConfigGroupRules(payload).post_raise(api, config_group_id=cfg_grp_Id)

        def associate_devices(devices_association_values: DeviceAssociationValuesModel, cfg_grp_Id: str):
            payload = {
                "devices": [
                    {"id": device_name_id.get(device_data.deviceName) if device_name_id.get(
                        device_data.deviceName) is not None
                    else raise_value_error(f"device Id for {device_data.deviceName} not found!")}
                    for device_data in devices_association_values.devices
                ]
            }
            ConfigGroupAssociated(payload).put_raise(api, configGroupId=cfg_grp_Id)

        def associate_device_variables(devices_association_values: DeviceAssociationValuesModel, cfg_grp_Id: str) -> \
        List[str]:
            def delete_suggestions():
                for device_data in devices_association_values.devices:
                    if device_data.variables:
                        for variable in device_data.variables:
                            del variable.suggestions

            delete_suggestions()
            payload = {
                "solution": devices_association_values.family,
                "devices": [
                    {"device-id": device_name_id.get(device_data.deviceName) if device_name_id.get(
                        device_data.deviceName) is not None
                    else raise_value_error(f"device Id for {device_data.deviceName} not found!"),
                     "variables": device_data.variables if device_data.variables
                     else raise_value_error(f"device variables for {device_data.deviceName} not found!")}
                    for device_data in devices_association_values.devices
                ]
            }
            uuids = []
            try:
                uuids = ConfigGroupValues(payload).put_raise(api, configGroupId=cfg_grp_Id)
            except (Exception) as ex:
                self.log_error(f"Failed: error with device variables: {ex}")
            return uuids

        if config_groups is None:
            raise ValueError(f"no {title} config-groups found in YML template file") from None

        deploy_data = []
        for cfg_grp in config_groups:
            cfg_grp_Id = cfg_group_name_id.get(cfg_grp.configGroupName) if cfg_group_name_id.get(
                cfg_grp.configGroupName) is not None else (
                raise_value_error(f"config group Id for {cfg_grp.configGroupName} not found!"))
            if cfg_grp.tag_rules:
                associate_tags(cfg_grp.tag_rules, cfg_grp_Id)
            if cfg_grp.devices_association_values and cfg_grp.devices_association_values.devices:
                associate_devices(cfg_grp.devices_association_values, cfg_grp_Id)
                uuids = associate_device_variables(cfg_grp.devices_association_values, cfg_grp_Id)
                if uuids:
                    deploy_data.append((cfg_grp_Id, cfg_grp.configGroupName, uuids))

        return deploy_data

    def attach_create(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info(f'Attach create task: "{parsed_args.save_attach_file if parsed_args.save_attach_file is not None else ""}"')

        control_inventory = ControlInventory.get_raise(api)
        edge_inventory = EdgeInventory.get_raise(api)
        is_vsmart = parsed_args.device_types in ('vsmart', 'all')
        is_edge = parsed_args.device_types in ('edge', 'all')
        vsmarts_map, vsmart_attach_map, cedge_map, cedge_attach_map, vedge_map, vedge_attach_map = device_maps(
                device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site, parsed_args.system_ip,
                            default=None),
                ({entry.uuid for entry in control_inventory.filtered_iter(ControlInventory.is_vsmart)},
                 {entry.uuid for entry in control_inventory.filtered_iter(ControlInventory.is_vsmart, ControlInventory.is_available)})
                if is_vsmart else (set(), set()),
                ({entry.uuid for entry in edge_inventory.filtered_iter(EdgeInventory.is_cedge)},
                 {entry.uuid for entry in edge_inventory.filtered_iter(EdgeInventory.is_cedge, EdgeInventory.is_available)})
                if is_edge else (set(), set()),
                ({entry.uuid for entry in edge_inventory.filtered_iter(EdgeInventory.is_not_cedge)},
                 {entry.uuid for entry in edge_inventory.filtered_iter(EdgeInventory.is_not_cedge, EdgeInventory.is_available)})
                if is_edge else (set(), set())
        )

        device_filter = True if parsed_args.devices or parsed_args.site or parsed_args.system_ip else False
        # Config Groups
        list_of_config_groups = []
        if cedge_map:
            try:
                cfg_group_index = ConfigGroupIndex.get_raise(api)
                if not is_index_supported(ConfigGroupIndex, version=api.server_version):
                    self.log_warning("Will skip config-groups, target vManage does not support config-groups")
                    raise StopIteration()
                selected_cfg_groups = (
                    (cfg_group_name, cfg_group_id)
                    for cfg_group_id, cfg_group_name in cfg_group_index
                    if parsed_args.config_groups is None or regex_search(parsed_args.config_groups, cfg_group_name)
                )
                deploy_data = self.get_cfg_group_deploy_data(api, selected_cfg_groups, parsed_args.config_groups,
                                                             device_filter, devices_set=set(cedge_map), devices_attach_set=set(cedge_attach_map))
                if deploy_data:
                    for group_name, tag_rules, saved_values in deploy_data:
                        if saved_values:
                            for device in saved_values["devices"]:
                                device["deviceName"] = cedge_map.get(device["device-id"])
                        data = [ConfigGroupsModel(configGroupName=group_name,
                                                  tag_rules=tag_rules[0] if tag_rules and len(tag_rules)>0 else None,
                                                  devices_association_values=saved_values)]
                        list_of_config_groups = list_of_config_groups + data
            except RestAPIException as ex:
                self.log_error(f"Failed: retrieve config groups: {ex}")
            except StopIteration:
                pass

        # Template attachments
        data = {}
        current_attach_templates = AttachTemplatesModel(**data)
        try:
            template_index = DeviceTemplateIndex.get_raise(api)
            edge_templates_attach = []
            for device_type, edge_type, device_map, device_attach_map in (
                                        (DeviceTemplateIndex.is_vsmart, None, vsmarts_map, vsmart_attach_map),
                                        (DeviceTemplateIndex.is_not_vsmart, DeviceTemplateIndex.is_not_vedge, cedge_map, cedge_attach_map),
                                        (DeviceTemplateIndex.is_not_vsmart, DeviceTemplateIndex.is_vedge, vedge_map, vedge_attach_map)):
                    if device_map:
                        filter_iter = (template_index.filtered_iter(device_type, edge_type)
                                       if edge_type is not None else template_index.filtered_iter(device_type))
                        selected_templates = (
                            (template_name, template_id)
                            for template_id, template_name in filter_iter
                            if parsed_args.templates is None or regex_search(parsed_args.templates, template_name)
                        )
                        attach_data = self.get_template_attach_data(api, selected_templates, parsed_args.templates, device_filter,
                                                                    uuid_set=set(device_map), attach_uuid_set=set(device_attach_map))
                        data = [
                            DeviceAttachTemplateModel(templateName=item[0], isCliTemplate=item[1],
                                                      device=item[2] if item[2] is not None else [])
                            for item in attach_data
                        ]
                        if edge_type:
                            edge_templates_attach = edge_templates_attach + data
                            current_attach_templates.edge_templates = edge_templates_attach
                        else:
                            current_attach_templates.vsmart_templates = data
        except RestAPIException as ex:
                self.log_error(f"Failed: retrieve device templates: {ex}")

        # vsmart policy
        current_vsmart_policy = None
        try:
            if is_vsmart:
                _, policy_name = PolicyVsmartIndex.get_raise(api).active_policy
                current_vsmart_policy = VsmartPolicyModel(name=policy_name, activate=True) if policy_name else VsmartPolicyModel()
        except RestAPIException as ex:
            self.log_error(f"Failed: retrieve vsmart active policy: {ex}")

        attach = AttachModel(attach_templates=current_attach_templates, config_groups=list_of_config_groups,
                             vsmart_policy=current_vsmart_policy)
        result = None
        if parsed_args.save_attach_file:
            with open(parsed_args.save_attach_file, 'w') as file:
                yaml.dump(attach.dict(),sort_keys=False,indent=2, stream=file)
            self.log_info(f'Attach file saved as "{parsed_args.save_attach_file}"')
        else:
            result = [yaml.dump(attach.dict(), sort_keys=False,indent=2)]

        return result


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
    def edge_sets(api: Rest) -> tuple[set[str], set[str]]:
        inventory = EdgeInventory.get_raise(api)
        attached_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_attached)
        }
        associated_set = {
            entry.uuid for entry in inventory.filtered_iter(EdgeInventory.is_associated)
        }
        return attached_set, associated_set

    @staticmethod
    def vsmart_sets(api: Rest) -> tuple[set[str], set[str]]:
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
    batch: Annotated[int, Field(ge=1, lt=9999)] = DEFAULT_BATCH_SIZE

    # Validators
    _validate_regex = field_validator('templates', 'config_groups', 'devices')(validate_regex)
    _validate_site_id = field_validator('site')(validate_site_id)
    _validate_ipv4 = field_validator('system_ip')(validate_ipv4)


class AttachVsmartArgs(AttachDetachArgs):
    workdir: str
    activate: bool = False
    template_filter: const(Callable, DeviceTemplateIndex.is_vsmart)
    device_sets: const(Callable, TaskAttach.vsmart_sets)
    set_title: const(str, 'vSmart')

    # Validators
    _validate_workdir = field_validator('workdir')(validate_workdir)


class AttachEdgeArgs(AttachDetachArgs):
    workdir: str
    template_filter: const(Callable, DeviceTemplateIndex.is_not_vsmart)
    device_sets: const(Callable, TaskAttach.edge_sets)
    set_title: const(str, 'WAN Edge')

    # Validators
    _validate_workdir = field_validator('workdir')(validate_workdir)


class DetachVsmartArgs(AttachDetachArgs):
    template_filter: const(Callable, DeviceTemplateIndex.is_vsmart)
    device_sets: const(Callable, TaskDetach.vsmart_sets)
    set_title: const(str, 'vSmart')


class DetachEdgeArgs(AttachDetachArgs):
    template_filter: const(Callable, DeviceTemplateIndex.is_not_vsmart)
    device_sets: const(Callable, TaskDetach.edge_sets)
    set_title: const(str, 'WAN Edge')
