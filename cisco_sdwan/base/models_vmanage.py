"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.models_vmanage
 This module implements vManage API models
"""
from typing import Iterable, Set
from pathlib import Path
from collections import namedtuple
from urllib.parse import quote_plus
from .catalog import register, op_register
from .models_base import (ApiItem, IndexApiItem, ConfigItem, IndexConfigItem, RealtimeItem, BulkStatsItem,
                          BulkStateItem, ApiPath, IdName)


#
# Non-config items
#
class DeviceModeCli(ApiItem):
    api_path = ApiPath(None, 'template/config/device/mode/cli', None, None)
    id_tag = 'id'

    @staticmethod
    def api_params(device_type, *device_ids):
        return {
            "deviceType": device_type,
            "devices": [{"deviceId": device_id} for device_id in device_ids]
        }


class DeviceTemplateAttach(ApiItem):
    api_path = ApiPath(None, 'template/device/config/attachfeature', None, None)
    id_tag = 'id'

    @staticmethod
    def api_params(template_input_iter, is_edited):
        """
        Build dictionary used to provide input parameters for api POST call
        :param template_input_iter: An iterable of (<template_id>, <input_list>) tuples. Input_list is a list where
                                    each entry represents one attached device and is a dictionary of input
                                    variable names and values.
        :param is_edited: True if this is an in-place re-attach, False if this is a template attach.
        :return: Dictionary used to provide POST input parameters
        """
        def template_entry(template_id, template_input_list):
            return {
                "templateId": template_id,
                "device": template_input_list,
                "isEdited": is_edited,
                "isMasterEdited": False,
            }

        return {
            "deviceTemplateList": [
                template_entry(item_id, input_list) for item_id, input_list in template_input_iter
            ]
        }


class DeviceTemplateCLIAttach(DeviceTemplateAttach):
    api_path = ApiPath(None, 'template/device/config/attachcli', None, None)


class PolicyVsmartDeactivate(ApiItem):
    api_path = ApiPath(None, 'template/policy/vsmart/deactivate', None, None)
    id_tag = 'id'


class PolicyVsmartActivate(ApiItem):
    api_path = ApiPath(None, 'template/policy/vsmart/activate', None, None)
    id_tag = 'id'

    @staticmethod
    def api_params(is_edited):
        return {"isEdited": True} if is_edited else {}


class PolicyVsmartStatus(ApiItem):
    api_path = ApiPath('template/policy/vsmart/connectivity/status', None, None, None)

    def raise_for_status(self):
        def vsmart_ready(vsmart_entry):
            return vsmart_entry['operationMode'] == 'vmanage'

        data_list = self.data.get('data', [])
        if len(data_list) == 0 or not all(vsmart_ready(entry) for entry in data_list):
            raise PolicyVsmartStatusException()


class PolicyVsmartStatusException(Exception):
    """ Exception indicating Vsmart status is not ready """
    pass


class EdgeCertificateSync(ApiItem):
    api_path = ApiPath(None, 'certificate/vedge/list?action=push', None, None)
    id_tag = 'id'


class ActionStatus(ApiItem):
    api_path = ApiPath('device/action/status', None, None, None)

    @property
    def status(self):
        return self.data.get('summary', {}).get('status', None)

    @property
    def is_completed(self):
        return self.status == 'done'

    @property
    def is_successful(self):
        def task_success(task_entry):
            return task_entry['statusId'] == 'success' or task_entry['statusId'] == 'success_scheduled'

        data_list = self.data.get('data', [])
        # When action validation fails, returned data is empty
        if len(data_list) == 0:
            return False

        return all(task_success(entry) for entry in data_list)

    @property
    def activity_details(self):
        def device_details(task_entry):
            return '{hostname}: {activity}'.format(hostname=task_entry.get('host-name', '<unknown>'),
                                                   activity=', '.join(task_entry.get('activity', [])))

        data_list = self.data.get('data', [])
        # When action validation fails, returned data is empty
        if len(data_list) == 0:
            return 'No data in action status'

        return ', '.join(device_details(entry) for entry in data_list)


class CheckVBond(ApiItem):
    api_path = ApiPath('template/device/config/vbond', None, None, None)

    @property
    def is_configured(self):
        return self.data.get('isVbondConfigured', False)


#
# Device Inventory
#
class Device(IndexApiItem):
    api_path = ApiPath('device', None, None, None)
    iter_fields = ('uuid', 'host-name')

    extended_iter_fields = ('deviceId', 'site-id', 'reachability', 'device-type', 'device-model')


class EdgeInventory(IndexApiItem):
    api_path = ApiPath('system/device/vedges', None, None, None)
    iter_fields = ('uuid', 'vedgeCertificateState')

    extended_iter_fields = ('host-name', 'system-ip')


class ControlInventory(IndexApiItem):
    api_path = ApiPath('system/device/controllers', None, None, None)
    iter_fields = ('uuid', 'validity')

    extended_iter_fields = ('host-name', 'system-ip')

    @staticmethod
    def is_vsmart(device_type):
        return device_type is not None and device_type == 'vsmart'

    @staticmethod
    def is_vbond(device_type):
        return device_type is not None and device_type == 'vbond'

    @staticmethod
    def is_manage(device_type):
        return device_type == 'vmanage'

    def filtered_iter(self, filter_fn):
        return (
            (item_id, item_name) for item_type, item_id, item_name
            in self.iter('deviceType', *self.iter_fields) if filter_fn(item_type)
        )


#
# Device configuration
#
class DeviceConfig(ConfigItem):
    api_path = ApiPath('template/config/attached', None, None, None)
    store_path = ('device_configs',)
    store_file = '{item_name}.txt'

    def save(self, node_dir, ext_name=False, item_name=None, item_id=None):
        """
        Save data (i.e. self.data) to a json file

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        :param item_name: (Optional) Name of the item being saved. Variable used to build the filename.
        :param item_id: (Optional) UUID for the item being saved. Variable used to build the filename.
        :return: True indicates data has been saved. False indicates no data to save (and no file has been created).
        """
        if self.is_empty:
            return False

        dir_path = Path(self.root_dir, node_dir, *self.store_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        with open(dir_path.joinpath(self.get_filename(ext_name, item_name, item_id)), 'w') as write_f:
            write_f.write(self.data['config'])

        return True

    @staticmethod
    def api_params(device_id):
        # Device uuid is not url-safe
        return quote_plus(device_id)


class DeviceConfigRFS(DeviceConfig):
    store_file = '{item_name}_rfs.txt'

    @staticmethod
    def api_params(device_id):
        # Device uuid is not url-safe
        return '{safe_device_id}?type=RFS'.format(safe_device_id=quote_plus(device_id))


#
# Templates
#
class CliOrFeatureApiPath:
    def __init__(self, api_path_feature, api_path_cli):
        self.api_path_feature = api_path_feature
        self.api_path_cli = api_path_cli

    def __get__(self, instance, owner):
        # If called from class, assume its a feature template
        is_cli_template = instance is not None and instance.is_type_cli

        return self.api_path_cli if is_cli_template else self.api_path_feature


# Set of device types that use cedge template class. Updated as of vManage 20.6.1
CEDGE_SET = {
    "vedge-CSR-1000v", "vedge-ISR-4331", "vedge-ISR-4431", "vedge-ISR-4461", "vedge-ISR-4451-X",
    "vedge-C8300-1N1S-4T2X", "vedge-IR-1101", "vedge-C8300-1N1S-6T", "vedge-ISRv", "vedge-ISR-4321", "vedge-ISR-4351",
    "vedge-ISR-4221", "vedge-ISR-4221X", "vedge-ASR-1001-X", "vedge-ASR-1002-X", "vedge-ASR-1002-HX",
    "vedge-ASR-1001-HX", "vedge-C8500-12X4QC", "vedge-C8500-12X", "vedge-C1101-4P", "vedge-C1101-4PLTEP",
    "vedge-C1111-4P", "vedge-C1161X-8P", "vedge-C1111-8P", "vedge-C1113-8PLTEEA", "vedge-C1121X-8P", "vedge-C1111X-8P",
    "vedge-C1111-8PW", "vedge-C1111-8PLTEEA", "vedge-C1121-8PLTEPW", "vedge-C1111-8PLTELAW", "vedge-C1111-8PLTEEAW",
    "vedge-C1111-8PLTELA", "vedge-C1111-4PLTEEA", "vedge-C1101-4PLTEPW", "vedge-C1109-4PLTE2PW", "vedge-C1109-4PLTE2P",
    "vedge-C1109-2PLTEVZ", "vedge-C1109-2PLTEUS", "vedge-C1109-2PLTEGB", "vedge-C1121X-8PLTEP", "vedge-C1161X-8PLTEP",
    "vedge-C1113-8PMLTEEA", "vedge-C1111-4PLTELA", "vedge-C1116-4P", "vedge-C1116-4PLTEEA", "vedge-C1121-8P",
    "vedge-C1121-8PLTEP", "vedge-C1128-8PLTEP", "vedge-C1121-4PLTEP", "vedge-C1121-4P", "vedge-C1126-8PLTEP",
    "vedge-C1127-8PLTEP", "vedge-C1161-8P", "vedge-C1117-4P", "vedge-C1117-4PM", "vedge-C1117-4PLTEEA",
    "vedge-C1126X-8PLTEP", "vedge-C1127X-8PLTEP", "vedge-C1121X-8PLTEPW", "vedge-C1127X-8PMLTEP", "vedge-C1127-8PMLTEP",
    "vedge-C1117-4PLTELA", "vedge-nfvis-ENCS5400", 'vedge-C1113-8PLTEW', 'vedge-ESR-6300', "vedge-C8300-2N2S-6T",
    "vedge-C8300-2N2S-4T2X", "vedge-C1117-4PMLTEEA", "vedge-C1113-8PW", "vedge-ISR1100-4GLTENA-XE",
    "vedge-C1117-4PMLTEEAWE", "vedge-ASR-1006-X", "vedge-ISR1100X-6G-XE", "vedge-C1113-8PM", "vedge-C1116-4PWE",
    "vedge-IR-1835", "vedge-C8500L-8S4X", "vedge-C1113-8PLTEEAW", "vedge-C1117-4PLTELAWZ", "vedge-C1112-8PWE",
    "cellular-gateway-CG522-E", "vedge-C1117-4PLTEEAW", "vedge-C1116-4PLTEEAWE", "vedge-C1112-8PLTEEAWE",
    "vedge-C1113-8PLTELAWZ", "cellular-gateway-CG418-E", "vedge-ISR1100-6G-XE", "vedge-C1113-8PMWE", "vedge-C1111-4PW",
    "vedge-C1113-8PLTELA", "vedge-C1118-8P", "vedge-C1112-8P", "vedge-ISR1100-4G-XE", "vedge-IR-1833",
    "vedge-ISR1100X-4G-XE", "vedge-C1117-4PMWE", "vedge-IR-1821", "vedge-C1161-8PLTEP", "vedge-ISR1100-4GLTEGB-XE",
    "vedge-nfvis-C8200-UCPE", "vedge-C8000V", "vedge-C1117-4PW", "vedge-C8200-1N-4T", "vedge-C1112-8PLTEEA",
    "vedge-C1113-8P", "vedge-IR-1831", "vedge-C8200L-1N-4T", "vedge-nfvis-C8200-UCPEVM", "vedge-C8200L-1N-4T",
    "vedge-nfvis-C8200-UCPEVM", "vedge-IR-8340"
}
# Software devices. Updated as of vManage 20.6.1
SOFT_EDGE_SET = {"vedge-CSR-1000v", "vedge-C8000V", "vedge-cloud", "vmanage", "vsmart"}


class DeviceTemplate(ConfigItem):
    api_path = CliOrFeatureApiPath(
        ApiPath('template/device/object', 'template/device/feature', 'template/device'),
        ApiPath('template/device/object', 'template/device/cli', 'template/device')
    )
    store_path = ('device_templates', 'template')
    store_file = '{item_name}.json'
    name_tag = 'templateName'
    post_filtered_tags = ('feature',)
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'templateAttached', 'templateConfigurationEdited'}

    @property
    def is_type_cli(self) -> bool:
        return self.data.get('configType', 'template') == 'file'

    @property
    def is_cedge(self) -> bool:
        return self.data['deviceType'] in CEDGE_SET

    def contains_template(self, template_type: str) -> bool:
        return template_type in self.find_key('templateType')

    @property
    def feature_templates(self) -> Set[str]:
        return set(self.find_key('templateId', from_key='generalTemplates'))


@register('template_device', 'device template', DeviceTemplate)
class DeviceTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/device', None, None, None)
    store_file = 'device_templates.json'
    iter_fields = IdName('templateId', 'templateName')

    @staticmethod
    def is_vsmart(device_type, num_attached):
        return device_type is not None and device_type == 'vsmart' and num_attached > 0

    @staticmethod
    def is_not_vsmart(device_type, num_attached):
        return device_type is not None and device_type != 'vsmart' and num_attached > 0

    @staticmethod
    def is_cedge(device_type, num_attached):
        return device_type in CEDGE_SET

    def filtered_iter(self, filter_fn):
        return (
            (item_id, item_name) for item_type, item_attached, item_id, item_name
            in self.iter('deviceType', 'devicesAttached', *self.iter_fields) if filter_fn(item_type, item_attached)
        )


# This is a special case handled under DeviceTemplate
class DeviceTemplateAttached(IndexConfigItem):
    api_path = ApiPath('template/device/config/attached', None, None, None)
    store_path = ('device_templates', 'attached')
    store_file = '{item_name}.json'
    iter_fields = ('uuid', 'personality')


# This is a special case handled under DeviceTemplate
class DeviceTemplateValues(ConfigItem):
    api_path = ApiPath(None, 'template/device/config/input', None, None)
    store_path = ('device_templates', 'values')
    store_file = '{item_name}.json'

    @staticmethod
    def api_params(template_id, device_uuid_list):
        """
        Build dictionary used to provide input parameters for api POST call
        :param template_id: String containing the template ID
        :param device_uuid_list: List of device UUIDs
        :return: Dictionary used to provide POST input parameters
        """
        return {
            "deviceIds": device_uuid_list,
            "isEdited": False,
            "isMasterEdited": False,
            "templateId": template_id
        }

    def input_list(self, allowed_uuid_set=None):
        """
        Return list of device input entries. Each entry represents one attached device and is a dictionary of input
        variable names and values.
        :param allowed_uuid_set: Optional, set of uuids. If provided, only input entries for those uuids are returned
        :return: [{<input_var_name>: <input_var_value>, ...}, ...]
        """
        return [entry for entry in self.data.get('data', [])
                if allowed_uuid_set is None or entry.get('csv-deviceId') in allowed_uuid_set]

    @staticmethod
    def input_list_devices(input_list: list) -> Iterable[str]:
        return (entry.get('csv-host-name') for entry in input_list)

    def values_iter(self):
        return (
            (entry.get('csv-deviceId'), entry.get('csv-host-name'), entry) for entry in self.data.get('data', [])
        )

    def title_dict(self):
        return {column['property']: column['title'] for column in self.data.get('header', {}).get('columns', [])}

    def __iter__(self):
        return self.values_iter()


class FeatureTemplate(ConfigItem):
    api_path = ApiPath('template/feature/object', 'template/feature')
    store_path = ('feature_templates',)
    store_file = '{item_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'
    type_tag = 'templateType'
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'devicesAttached', 'attachedMastersCount'}

    @property
    def device_types(self) -> Set[str]:
        return set(self.data.get('deviceType', []))

    @device_types.setter
    def device_types(self, device_type_iter: Iterable[str]) -> None:
        self.data['deviceType'] = [device_type for device_type in device_type_iter]

    @property
    def masters_attached(self) -> int:
        """
        Returns number of device templates (i.e. master templates) that utilize this feature template
        """
        return self.data.get('attachedMastersCount')

    @property
    def devices_attached(self) -> int:
        """
        Returns number of devices attached to device templates attached to this feature template
        """
        return self.data.get('devicesAttached')


@register('template_feature', 'feature template', FeatureTemplate)
class FeatureTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/feature', None, None, None)
    store_file = 'feature_templates.json'
    iter_fields = IdName('templateId', 'templateName')

    @staticmethod
    def filter_type_default(desired_type: str, desired_is_default: bool, item_type: str, item_is_default: bool) -> bool:
        """
        Intended to be used along with partial to create a filter_fn that matches on desired_type and
        desired_is_default values. Partial locks the desired_type and desired_is_default parameters.
        :param desired_type: Desired feature templateType
        :param desired_is_default: Whether to match only factoryDefault templates
        :param item_type: templateType from feature template being matched
        :param item_is_default: factoryDefault from feature template being matched
        :returns: True if conditions matched, false otherwise
        """
        if desired_is_default and not item_is_default:
            return False

        return desired_type == item_type

    def filtered_iter(self, filter_fn):
        return (
            (item_id, item_name) for item_type, item_is_default, item_id, item_name
            in self.iter('templateType', 'factoryDefault', *self.iter_fields) if filter_fn(item_type, item_is_default)
        )


#
# Policy vSmart
#

class PolicyVsmart(ConfigItem):
    api_path = ApiPath('template/policy/vsmart/definition', 'template/policy/vsmart')
    store_path = ('policy_templates', 'vSmart')
    store_file = '{item_name}.json'
    name_tag = 'policyName'
    type_tag = 'policyType'
    skip_cmp_tag_set = {'isPolicyActivated', }


@register('policy_vsmart', 'VSMART policy', PolicyVsmart)
class PolicyVsmartIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vsmart', None, None, None)
    store_file = 'policy_templates_vsmart.json'
    iter_fields = IdName('policyId', 'policyName')

    @property
    def active_policy(self):
        """
        Return ID and name from active policy or (None, None) if no policy is active
        :return: (<id>, <name>) or (None, None)
        """
        for is_active, item_id, item_name in self.iter('isPolicyActivated', *self.iter_fields):
            if is_active:
                return item_id, item_name
        return None, None


#
# Policy vEdge
#

class PolicyVedge(ConfigItem):
    api_path = ApiPath('template/policy/vedge/definition', 'template/policy/vedge')
    store_path = ('policy_templates', 'vEdge')
    store_file = '{item_name}.json'
    name_tag = 'policyName'
    type_tag = 'policyType'


@register('policy_vedge', 'edge policy', PolicyVedge)
class PolicyVedgeIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vedge', None, None, None)
    store_file = 'policy_templates_vedge.json'
    iter_fields = IdName('policyId', 'policyName')


#
# Policy Security
#

class PolicySecurity(ConfigItem):
    api_path = ApiPath('template/policy/security/definition', 'template/policy/security')
    store_path = ('policy_templates', 'Security')
    store_file = '{item_name}.json'
    name_tag = 'policyName'
    type_tag = 'policyType'


@register('policy_security', 'security policy', PolicySecurity)
class PolicySecurityIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/security', None, None, None)
    store_file = 'policy_templates_security.json'
    iter_fields = IdName('policyId', 'policyName')


#
# Policy Voice
#

class PolicyVoice(ConfigItem):
    api_path = ApiPath('template/policy/voice/definition', 'template/policy/voice')
    store_path = ('policy_templates', 'Voice')
    store_file = '{item_name}.json'
    name_tag = 'policyName'
    type_tag = 'policyType'


@register('policy_voice', 'voice policy', PolicyVoice, min_version='20.1')
class PolicyVoiceIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/voice', None, None, None)
    store_file = 'policy_templates_voice.json'
    iter_fields = IdName('policyId', 'policyName')


#
# Policy Custom Application
#

class PolicyCustomApp(ConfigItem):
    api_path = ApiPath('template/policy/customapp')
    store_path = ('policy_templates', 'CustomApp')
    store_file = '{item_name}.json'
    name_tag = 'appName'
    id_tag = 'appId'
    skip_cmp_tag_set = {'lastUpdated', }

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this API item.
        """
        # In 20.3.1 the payload returned by vManage contains a 'data' key with the policy definition in it. This is
        # different than on previous versions or other ConfigItems. Overwriting the default __init__ in order to
        # handle both options.
        super().__init__(data.get('data', data))


@register('policy_customapp', 'custom application policy', PolicyCustomApp, min_version='20.1')
class PolicyCustomAppIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/customapp', None, None, None)
    store_file = 'policy_templates_customapp.json'
    iter_fields = IdName('appId', 'appName')


#
# Policy definitions
#

# Policy definition base class
class PolicyDef(ConfigItem):
    store_file = '{item_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'
    type_tag = 'type'
    skip_cmp_tag_set = {'lastUpdated', 'referenceCount', 'references', 'activatedId', 'isActivatedByVsmart',
                        'owner', 'infoTag'}


# Policy definition index base class
class PolicyDefIndex(IndexConfigItem):
    iter_fields = IdName('definitionId', 'name')


class PolicyDefData(PolicyDef):
    api_path = ApiPath('template/policy/definition/data')
    store_path = ('policy_definitions', 'Data')


@register('policy_definition', 'data policy definition', PolicyDefData)
class PolicyDefDataIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/data', None, None, None)
    store_file = 'policy_definitions_data.json'


class PolicyDefMesh(PolicyDef):
    api_path = ApiPath('template/policy/definition/mesh')
    store_path = ('policy_definitions', 'Mesh')


@register('policy_definition', 'mesh policy definition', PolicyDefMesh)
class PolicyDefMeshIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/mesh', None, None, None)
    store_file = 'policy_definitions_mesh.json'


class PolicyDefRewriteRule(PolicyDef):
    api_path = ApiPath('template/policy/definition/rewriterule')
    store_path = ('policy_definitions', 'RewriteRule')


@register('policy_definition', 'rewrite-rule policy definition', PolicyDefRewriteRule)
class PolicyDefRewriteRuleIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/rewriterule', None, None, None)
    store_file = 'policy_definitions_rewriterule.json'


class PolicyDefAclv6(PolicyDef):
    api_path = ApiPath('template/policy/definition/aclv6')
    store_path = ('policy_definitions', 'ACLv6')


@register('policy_definition', 'ACLv6 policy definition', PolicyDefAclv6)
class PolicyDefAclv6Index(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/aclv6', None, None, None)
    store_file = 'policy_definitions_aclv6.json'


class PolicyDefQosmap(PolicyDef):
    api_path = ApiPath('template/policy/definition/qosmap')
    store_path = ('policy_definitions', 'QoSMap')


@register('policy_definition', 'QOS-map policy definition', PolicyDefQosmap)
class PolicyDefQosmapIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/qosmap', None, None, None)
    store_file = 'policy_definitions_qosmap.json'


class PolicyDefUrlfiltering(PolicyDef):
    api_path = ApiPath('template/policy/definition/urlfiltering')
    store_path = ('policy_definitions', 'URLFiltering')


@register('policy_definition', 'URL-filtering policy definition', PolicyDefUrlfiltering)
class PolicyDefUrlfilteringIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/urlfiltering', None, None, None)
    store_file = 'policy_definitions_urlfiltering.json'


class PolicyDefZonebasedfw(PolicyDef):
    api_path = ApiPath('template/policy/definition/zonebasedfw')
    store_path = ('policy_definitions', 'ZoneBasedFW')


@register('policy_definition', 'zone-based FW policy definition', PolicyDefZonebasedfw)
class PolicyDefZonebasedfwIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/zonebasedfw', None, None, None)
    store_file = 'policy_definitions_zonebasedfw.json'


class PolicyDefApproute(PolicyDef):
    api_path = ApiPath('template/policy/definition/approute')
    store_path = ('policy_definitions', 'AppRoute')


@register('policy_definition', 'appRoute policy definition', PolicyDefApproute)
class PolicyDefApprouteIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/approute', None, None, None)
    store_file = 'policy_definitions_approute.json'


class PolicyDefVpnmembershipgroup(PolicyDef):
    api_path = ApiPath('template/policy/definition/vpnmembershipgroup')
    store_path = ('policy_definitions', 'VPNMembershipGroup')


@register('policy_definition', 'VPN membership policy definition', PolicyDefVpnmembershipgroup)
class PolicyDefVpnmembershipgroupIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/vpnmembershipgroup', None, None, None)
    store_file = 'policy_definitions_vpnmembershipgroup.json'


class PolicyDefAcl(PolicyDef):
    api_path = ApiPath('template/policy/definition/acl')
    store_path = ('policy_definitions', 'ACL')


@register('policy_definition', 'ACL policy definition', PolicyDefAcl)
class PolicyDefAclIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/acl', None, None, None)
    store_file = 'policy_definitions_acl.json'


class PolicyDefHubandspoke(PolicyDef):
    api_path = ApiPath('template/policy/definition/hubandspoke')
    store_path = ('policy_definitions', 'HubAndSpoke')


@register('policy_definition', 'Hub-and-spoke policy definition', PolicyDefHubandspoke)
class PolicyDefHubandspokeIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/hubandspoke', None, None, None)
    store_file = 'policy_definitions_hubandspoke.json'


class PolicyDefVedgeroute(PolicyDef):
    api_path = ApiPath('template/policy/definition/vedgeroute')
    store_path = ('policy_definitions', 'vEdgeRoute')


@register('policy_definition', 'edge-route policy definition', PolicyDefVedgeroute)
class PolicyDefVedgerouteIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/vedgeroute', None, None, None)
    store_file = 'policy_definitions_vedgeroute.json'


class PolicyDefIntrusionprevention(PolicyDef):
    api_path = ApiPath('template/policy/definition/intrusionprevention')
    store_path = ('policy_definitions', 'IntrusionPrevention')


@register('policy_definition', 'IPS policy definition', PolicyDefIntrusionprevention)
class PolicyDefIntrusionpreventionIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/intrusionprevention', None, None, None)
    store_file = 'policy_definitions_intrusionprevention.json'


class PolicyDefControl(PolicyDef):
    api_path = ApiPath('template/policy/definition/control')
    store_path = ('policy_definitions', 'Control')


@register('policy_definition', 'control policy definition', PolicyDefControl)
class PolicyDefControlIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/control', None, None, None)
    store_file = 'policy_definitions_control.json'


class PolicyDefDnssecurity(PolicyDef):
    api_path = ApiPath('template/policy/definition/dnssecurity')
    store_path = ('policy_definitions', 'DNSSecurity')


@register('policy_definition', 'dns-security policy definition', PolicyDefDnssecurity)
class PolicyDefDnssecurityIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/dnssecurity', None, None, None)
    store_file = 'policy_definitions_dnssecurity.json'


class PolicyDefCflowd(PolicyDef):
    api_path = ApiPath('template/policy/definition/cflowd')
    store_path = ('policy_definitions', 'Cflowd')


@register('policy_definition', 'cflowd policy definition', PolicyDefCflowd)
class PolicyDefCflowdIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/cflowd', None, None, None)
    store_file = 'policy_definitions_cflowd.json'


class PolicyDefAMP(PolicyDef):
    api_path = ApiPath('template/policy/definition/advancedMalwareProtection')
    store_path = ('policy_definitions', 'AMP')


@register('policy_definition', 'AMP policy definition', PolicyDefAMP)
class PolicyDefAMPIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/advancedMalwareProtection', None, None, None)
    store_file = 'policy_definitions_amp.json'


class PolicyDefDeviceAccess(PolicyDef):
    api_path = ApiPath('template/policy/definition/deviceaccesspolicy')
    store_path = ('policy_definitions', 'DeviceAccess')


@register('policy_definition', 'device access policy definition', PolicyDefDeviceAccess)
class PolicyDefDeviceAccessIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/deviceaccesspolicy', None, None, None)
    store_file = 'policy_definitions_deviceaccess.json'


class PolicyDefDeviceAccessV6(PolicyDef):
    api_path = ApiPath('template/policy/definition/deviceaccesspolicyv6')
    store_path = ('policy_definitions', 'DeviceAccessV6')


@register('policy_definition', 'IPv6 device access policy definition', PolicyDefDeviceAccessV6)
class PolicyDefDeviceAccessV6Index(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/deviceaccesspolicyv6', None, None, None)
    store_file = 'policy_definitions_deviceaccessv6.json'


class PolicyDefDialPeer(PolicyDef):
    api_path = ApiPath('template/policy/definition/dialpeer')
    store_path = ('policy_definitions', 'DialPeer')


@register('policy_definition', 'dial-peer policy definition', PolicyDefDialPeer, min_version='20.1')
class PolicyDefDialPeerIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/dialpeer', None, None, None)
    store_file = 'policy_definitions_dialpeer.json'


class PolicyDefPhoneProfile(PolicyDef):
    api_path = ApiPath('template/policy/definition/srstphoneprofile')
    store_path = ('policy_definitions', 'PhoneProfile')


@register('policy_definition', 'phone profile policy definition', PolicyDefPhoneProfile, min_version='20.1')
class PolicyDefPhoneProfileIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/srstphoneprofile', None, None, None)
    store_file = 'policy_definitions_phoneprofile.json'


class PolicyDefFXOPort(PolicyDef):
    api_path = ApiPath('template/policy/definition/fxoport')
    store_path = ('policy_definitions', 'FXOPort')


@register('policy_definition', 'FXO port policy definition', PolicyDefFXOPort, min_version='20.1')
class PolicyDefFXOPortIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/fxoport', None, None, None)
    store_file = 'policy_definitions_fxoport.json'


class PolicyDefFXSPort(PolicyDef):
    api_path = ApiPath('template/policy/definition/fxsport')
    store_path = ('policy_definitions', 'FXSPort')


@register('policy_definition', 'FXS port policy definition', PolicyDefFXSPort, min_version='20.1')
class PolicyDefFXSPortIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/fxsport', None, None, None)
    store_file = 'policy_definitions_fxsport.json'


class PolicyDefFXSDIDPort(PolicyDef):
    api_path = ApiPath('template/policy/definition/fxsdidport')
    store_path = ('policy_definitions', 'FXSDIDPort')


@register('policy_definition', 'FXS-DID port policy definition', PolicyDefFXSDIDPort, min_version='20.1')
class PolicyDefFXSDIDPortIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/fxsdidport', None, None, None)
    store_file = 'policy_definitions_fxsdidport.json'


class PolicyDefSSLDecryption(PolicyDef):
    api_path = ApiPath('template/policy/definition/ssldecryption')
    store_path = ('policy_definitions', 'SSLDecryption')


@register('policy_definition', 'SSL decryption policy definition', PolicyDefSSLDecryption, min_version='20.1')
class PolicyDefSSLDecryptionIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/ssldecryption', None, None, None)
    store_file = 'policy_definitions_ssldecryption.json'


class PolicyDefUTDProfile(PolicyDef):
    api_path = ApiPath('template/policy/definition/sslutdprofile')
    store_path = ('policy_definitions', 'SSLUTDProfile')


@register('policy_definition', 'SSL decryption UTD profile policy definition', PolicyDefUTDProfile, min_version='20.1')
class PolicyDefUTDProfileIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/sslutdprofile', None, None, None)
    store_file = 'policy_definitions_sslutdprofile.json'


class PolicyDefPriisdnPort(PolicyDef):
    api_path = ApiPath('template/policy/definition/priisdnport')
    store_path = ('policy_definitions', 'PriisdnPort')


@register('policy_definition', 'pri isdn port policy definition', PolicyDefPriisdnPort, min_version='20.3')
class PolicyDefPriisdnPortIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/priisdnport', None, None, None)
    store_file = 'policy_definitions_priisdnport.json'


class PolicyDefRuleSet(PolicyDef):
    api_path = ApiPath('template/policy/definition/ruleset')
    store_path = ('policy_definitions', 'RuleSet')


@register('policy_definition', 'rule-set security policy definition', PolicyDefRuleSet, min_version='20.4')
class PolicyDefRuleSetIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/ruleset', None, None, None)
    store_file = 'policy_definitions_ruleset.json'


#
# Policy lists
#

# Policy list base class
class PolicyList(ConfigItem):
    store_file = '{item_name}.json'
    id_tag = 'listId'
    name_tag = 'name'
    type_tag = 'type'
    skip_cmp_tag_set = {'lastUpdated', 'referenceCount', 'references', 'activatedId', 'isActivatedByVsmart',
                        'owner', 'infoTag'}


# Policy list index base class
class PolicyListIndex(IndexConfigItem):
    iter_fields = IdName('listId', 'name')


class PolicyListVpn(PolicyList):
    api_path = ApiPath('template/policy/list/vpn')
    store_path = ('policy_lists', 'VPN')


@register('policy_list', 'VPN list', PolicyListVpn)
class PolicyListVpnIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/vpn', None, None, None)
    store_file = 'policy_lists_vpn.json'


class PolicyListUrlWhiteList(PolicyList):
    api_path = ApiPath('template/policy/list/urlwhitelist')
    store_path = ('policy_lists', 'URLWhitelist')


@register('policy_list', 'URL-whitelist list', PolicyListUrlWhiteList)
class PolicyListUrlWhileListIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/urlwhitelist', None, None, None)
    store_file = 'policy_lists_urlwhitelist.json'


class PolicyListUrlBlackList(PolicyList):
    api_path = ApiPath('template/policy/list/urlblacklist')
    store_path = ('policy_lists', 'URLBlacklist')


@register('policy_list', 'URL-blacklist list', PolicyListUrlBlackList)
class PolicyListUrlBlackListIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/urlblacklist', None, None, None)
    store_file = 'policy_lists_urlblacklist.json'


class PolicyListPolicer(PolicyList):
    api_path = ApiPath('template/policy/list/policer')
    store_path = ('policy_lists', 'Policer')


@register('policy_list', 'policer list', PolicyListPolicer)
class PolicyListPolicerIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/policer', None, None, None)
    store_file = 'policy_lists_policer.json'


class PolicyListIpsSignature(PolicyList):
    api_path = ApiPath('template/policy/list/ipssignature')
    store_path = ('policy_lists', 'IPSSignature')


@register('policy_list', 'IPS-signature list', PolicyListIpsSignature)
class PolicyListIpsSignatureIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/ipssignature', None, None, None)
    store_file = 'policy_lists_ipssignature.json'


class PolicyListClass(PolicyList):
    api_path = ApiPath('template/policy/list/class')
    store_path = ('policy_lists', 'Class')


@register('policy_list', 'class list', PolicyListClass)
class PolicyListClassIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/class', None, None, None)
    store_file = 'policy_lists_class.json'


class PolicyListUmbrellaData(PolicyList):
    api_path = ApiPath('template/policy/list/umbrelladata')
    store_path = ('policy_lists', 'UmbrellaData')


@register('policy_list', 'umbrella-data list', PolicyListUmbrellaData)
class PolicyListUmbrellaDataIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/umbrelladata', None, None, None)
    store_file = 'policy_lists_umbrelladata.json'


class PolicyListSite(PolicyList):
    api_path = ApiPath('template/policy/list/site')
    store_path = ('policy_lists', 'Site')


@register('policy_list', 'site list', PolicyListSite)
class PolicyListSiteIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/site', None, None, None)
    store_file = 'policy_lists_site.json'


class PolicyListExtcommunity(PolicyList):
    api_path = ApiPath('template/policy/list/extcommunity')
    store_path = ('policy_lists', 'ExtCommunity')


@register('policy_list', 'extended-community list', PolicyListExtcommunity)
class PolicyListExtcommunityIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/extcommunity', None, None, None)
    store_file = 'policy_lists_extcommunity.json'


# Data Prefix All (template/policy/list/dataprefixall) was purposely not included as it seems to collide with, meaning
# error, Data Prefix (template/policy/list/dataprefix).
# Data Prefix FQDN (template/policy/list/dataprefixfqdn) was also not included for the same reason.
class PolicyListDataprefix(PolicyList):
    api_path = ApiPath('template/policy/list/dataprefix')
    store_path = ('policy_lists', 'DataPrefix')


@register('policy_list', 'data-prefix list', PolicyListDataprefix)
class PolicyListDataprefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataprefix', None, None, None)
    store_file = 'policy_lists_dataprefix.json'


class PolicyListDataipv6prefix(PolicyList):
    api_path = ApiPath('template/policy/list/dataipv6prefix')
    store_path = ('policy_lists', 'DataIPv6Prefix')


@register('policy_list', 'data-ipv6-prefix list', PolicyListDataipv6prefix)
class PolicyListDataipv6prefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataipv6prefix', None, None, None)
    store_file = 'policy_lists_dataipv6prefix.json'


class PolicyListMirror(PolicyList):
    api_path = ApiPath('template/policy/list/mirror')
    store_path = ('policy_lists', 'Mirror')


@register('policy_list', 'mirror list', PolicyListMirror)
class PolicyListMirrorIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/mirror', None, None, None)
    store_file = 'policy_lists_mirror.json'


class PolicyListApplication(PolicyList):
    api_path = ApiPath('template/policy/list/app')
    store_path = ('policy_lists', 'App')


@register('policy_list', 'application list', PolicyListApplication)
class PolicyListApplicationIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/app', None, None, None)
    store_file = 'policy_lists_app.json'


class PolicyListLocalApplication(PolicyList):
    api_path = ApiPath('template/policy/list/localapp')
    store_path = ('policy_lists', 'LocalApp')


@register('policy_list', 'local-application list', PolicyListLocalApplication)
class PolicyListLocalApplicationIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/localapp', None, None, None)
    store_file = 'policy_lists_localapp.json'


class PolicyListSla(PolicyList):
    api_path = ApiPath('template/policy/list/sla')
    store_path = ('policy_lists', 'SLA')


@register('policy_list', 'SLA-class list', PolicyListSla)
class PolicyListSlaIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/sla', None, None, None)
    store_file = 'policy_lists_sla.json'


class PolicyListColor(PolicyList):
    api_path = ApiPath('template/policy/list/color')
    store_path = ('policy_lists', 'Color')


@register('policy_list', 'color list', PolicyListColor)
class PolicyListColorIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/color', None, None, None)
    store_file = 'policy_lists_color.json'


class PolicyListZone(PolicyList):
    api_path = ApiPath('template/policy/list/zone')
    store_path = ('policy_lists', 'Zone')


@register('policy_list', 'zone list', PolicyListZone)
class PolicyListZoneIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/zone', None, None, None)
    store_file = 'policy_lists_zone.json'


class PolicyListAspath(PolicyList):
    api_path = ApiPath('template/policy/list/aspath')
    store_path = ('policy_lists', 'ASPath')


@register('policy_list', 'as-path list', PolicyListAspath)
class PolicyListAspathIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/aspath', None, None, None)
    store_file = 'policy_lists_aspath.json'


class PolicyListTloc(PolicyList):
    api_path = ApiPath('template/policy/list/tloc')
    store_path = ('policy_lists', 'TLOC')


@register('policy_list', 'TLOC list', PolicyListTloc)
class PolicyListTlocIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/tloc', None, None, None)
    store_file = 'policy_lists_tloc.json'


# IP Prefix All (template/policy/list/ipprefixall) was purposely not included as it seems to collide with, meaning
# error, IP Prefix (template/policy/list/prefix).
class PolicyListPrefix(PolicyList):
    api_path = ApiPath('template/policy/list/prefix')
    store_path = ('policy_lists', 'Prefix')


@register('policy_list', 'prefix list', PolicyListPrefix)
class PolicyListPrefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/prefix', None, None, None)
    store_file = 'policy_lists_prefix.json'


class PolicyListIpv6prefix(PolicyList):
    api_path = ApiPath('template/policy/list/ipv6prefix')
    store_path = ('policy_lists', 'IPv6Prefix')


@register('policy_list', 'ipv6-prefix list', PolicyListIpv6prefix)
class PolicyListIpv6prefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/ipv6prefix', None, None, None)
    store_file = 'policy_lists_ipv6prefix.json'


class PolicyListFQDN(PolicyList):
    api_path = ApiPath('template/policy/list/fqdn')
    store_path = ('policy_lists', 'FQDN')


@register('policy_list', 'FQDN list', PolicyListFQDN, min_version='20.1')
class PolicyListFQDNIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/fqdn', None, None, None)
    store_file = 'policy_lists_fqdn.json'


class PolicyListLocaldomain(PolicyList):
    api_path = ApiPath('template/policy/list/localdomain')
    store_path = ('policy_lists', 'LocalDomain')


@register('policy_list', 'local-domain list', PolicyListLocaldomain)
class PolicyListLocaldomainIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/localdomain', None, None, None)
    store_file = 'policy_lists_localdomain.json'


class PolicyListCommunity(PolicyList):
    api_path = ApiPath('template/policy/list/community')
    store_path = ('policy_lists', 'Community')


@register('policy_list', 'community list', PolicyListCommunity)
class PolicyListCommunityIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/community', None, None, None)
    store_file = 'policy_lists_community.json'


# Umbrella Secret endpoints were removed in 19.3. Will leave it for now.
class PolicyListUmbrellaSecret(PolicyList):
    api_path = ApiPath('template/policy/list/umbrellasecret')
    store_path = ('policy_lists', 'UmbrellaSecret')


@register('policy_list', 'umbrella secret list', PolicyListUmbrellaSecret)
class PolicyListUmbrellaSecretIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/umbrellasecret', None, None, None)
    store_file = 'policy_lists_umbrellasecret.json'


class PolicyListTGApiKey(PolicyList):
    api_path = ApiPath('template/policy/list/tgapikey')
    store_path = ('policy_lists', 'TGApiKey')


@register('policy_list', 'threat grid api key list', PolicyListTGApiKey)
class PolicyListTGApiKeyIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/tgapikey', None, None, None)
    store_file = 'policy_lists_tgapikey.json'


class PolicyListTransRules(PolicyList):
    api_path = ApiPath('template/policy/list/translationrules')
    store_path = ('policy_lists', 'TranslationRules')


@register('policy_list', 'translation rules list', PolicyListTransRules, min_version='20.1')
class PolicyListTransRulesIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/translationrules', None, None, None)
    store_file = 'policy_lists_translationrules.json'


class PolicyListTransProfile(PolicyList):
    api_path = ApiPath('template/policy/list/translationprofile')
    store_path = ('policy_lists', 'TranslationProfile')


@register('policy_profile', 'translation profile', PolicyListTransProfile, min_version='20.1')
class PolicyListTransProfileIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/translationprofile', None, None, None)
    store_file = 'policy_lists_translationprofile.json'


class PolicyListSupervisoryDisc(PolicyList):
    api_path = ApiPath('template/policy/list/supervisorydisc')
    store_path = ('policy_lists', 'SupervisoryDisconnect')


@register('policy_list', 'supervisory disconnect list', PolicyListSupervisoryDisc, min_version='20.1')
class PolicyListSupervisoryDiscIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/supervisorydisc', None, None, None)
    store_file = 'policy_lists_supervisorydisconnect.json'


class PolicyListMediaProfile(PolicyList):
    api_path = ApiPath('template/policy/list/mediaprofile')
    store_path = ('policy_lists', 'MediaProfile')


@register('policy_list', 'media profile list', PolicyListMediaProfile, min_version='20.1')
class PolicyListMediaProfileIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/mediaprofile', None, None, None)
    store_file = 'policy_lists_mediaprofile.json'


class PolicyListFaxProtocol(PolicyList):
    api_path = ApiPath('template/policy/list/faxprotocol')
    store_path = ('policy_lists', 'FaxProtocol')


@register('policy_list', 'fax protocol list', PolicyListFaxProtocol, min_version='20.3')
class PolicyListFaxProtocolIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/faxprotocol', None, None, None)
    store_file = 'policy_lists_faxprotocol.json'


class PolicyListModemPassthrough(PolicyList):
    api_path = ApiPath('template/policy/list/modempassthrough')
    store_path = ('policy_lists', 'ModemPassthrough')


@register('policy_list', 'modem passthrough list', PolicyListModemPassthrough, min_version='20.3')
class PolicyListModemPassthroughIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/modempassthrough', None, None, None)
    store_file = 'policy_lists_modempassthrough.json'


class PolicyListTrunkGroup(PolicyList):
    api_path = ApiPath('template/policy/list/trunkgroup')
    store_path = ('policy_lists', 'TrunkGroup')


@register('policy_list', 'trunk group list', PolicyListTrunkGroup, min_version='20.3')
class PolicyListTrunkGroupIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/trunkgroup', None, None, None)
    store_file = 'policy_lists_trunkgroup.json'


class PolicyAppProbe(PolicyList):
    api_path = ApiPath('template/policy/list/appprobe')
    store_path = ('policy_lists', 'AppProbe')


@register('policy_list', 'app-probe class list', PolicyAppProbe, min_version='20.4')
class PolicyAppProbeIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/appprobe', None, None, None)
    store_file = 'policy_lists_appprobe.json'


class PolicyListPort(PolicyList):
    api_path = ApiPath('template/policy/list/port')
    store_path = ('policy_lists', 'Port')


@register('policy_list', 'port security list', PolicyListPort, min_version='20.4')
class PolicyListPortIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/port', None, None, None)
    store_file = 'policy_lists_port.json'


class PolicyListProtocol(PolicyList):
    api_path = ApiPath('template/policy/list/protocolname')
    store_path = ('policy_lists', 'Protocol')


@register('policy_list', 'protocol security list', PolicyListProtocol, min_version='20.4')
class PolicyListProtocolIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/protocolname', None, None, None)
    store_file = 'policy_lists_protocol.json'


class PolicyListExpandedCommunity(PolicyList):
    api_path = ApiPath('/template/policy/list/expandedcommunity')
    store_path = ('policy_lists', 'ExpandedCommunity')


@register('policy_list', 'expanded community list', PolicyListExpandedCommunity, min_version='20.5')
class PolicyListExpandedCommunityIndex(PolicyListIndex):
    api_path = ApiPath('/template/policy/list/expandedcommunity', None, None, None)
    store_file = 'policy_lists_expanded_community.json'


class PolicyListGeoLocation(PolicyList):
    api_path = ApiPath('/template/policy/list/geolocation')
    store_path = ('policy_lists', 'GeoLocation')


@register('policy_list', 'geo location list', PolicyListGeoLocation, min_version='20.5')
class PolicyListGeoLocationIndex(PolicyListIndex):
    api_path = ApiPath('/template/policy/list/geolocation', None, None, None)
    store_file = 'policy_lists_geo_location.json'


#
# Admin Settings
#
class SettingsVbond(ConfigItem):
    api_path = ApiPath('settings/configuration/device', None, 'settings/configuration/device', None)
    store_path = ('settings',)
    store_file = 'vbond.json'

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this API item.
        """
        # Get requests return a dict as {'data': [{'domainIp': 'vbond.cisco.com', 'port': '12346'}]}
        super().__init__(data.get('data', [''])[0])

    @property
    def is_configured(self):
        domain_ip = self.data.get('domainIp', '')
        return len(domain_ip) > 0 and domain_ip != 'Not Configured'


#
# Edge Certificate
#
class EdgeCertificate(IndexConfigItem):
    api_path = ApiPath('certificate/vedge/list', 'certificate/save/vedge/list', None, None)
    store_path = ('certificates',)
    store_file = 'edge_certificates.json'
    iter_fields = ('uuid', 'validity')

    extended_iter_fields = ('host-name', 'chasisNumber', 'serialNumber', 'vedgeCertificateState')

    _state_lookup = {
        'tokengenerated': 'token generated',
        'bootstrapconfiggenerated': 'bootstrap config generated',
        'csrgenerated': 'CSR generated',
        'csrfailed': 'CSR failed',
        'certinstallfailed': 'certificate install failed',
        'certinstalled': 'certificate installed',
    }

    @classmethod
    def state_str(cls, state):
        """
        Convert the state field from WAN edge certificate into user-friendly string. If not known, return the original
        state field
        :param state: string containing the WAN edge certificate state field.
        :return: string
        """
        return cls._state_lookup.get(state, state)

    def status_post_data(self, *new_status):
        """
        Build payload to be used for POST requests that update WAN edge certificate validity status
        :param new_status: One or more (<uuid>, <new status>) tuples
        :return: List containing payload for POST requests
        """
        new_status_dict = dict(new_status)

        return [
            {
                'chasisNumber': chassis,
                'serialNumber': serial,
                'validity': new_status_dict[uuid]
            }
            for uuid, status, hostname, chassis, serial, state in self.extended_iter() if uuid in new_status_dict
        ]


#
# Realtime items
#
@op_register('system', 'status', 'System status')
class SystemStatus(RealtimeItem):
    api_path = ApiPath('device/system/status', None, None, None)
    fields_std = ('state', 'cpu_user', 'cpu_system', 'mem_total', 'mem_free')
    fields_ext = ('disk_size', 'disk_used')


@op_register('bfd', 'sessions', 'BFD sessions')
class BfdSessions(RealtimeItem):
    api_path = ApiPath('device/bfd/sessions', None, None, None)
    fields_std = ('system_ip', 'site_id', 'local_color', 'color', 'state')
    fields_ext = ('src_ip', 'src_port', 'dst_ip', 'dst_port')


@op_register('control', 'connections', 'Control connections')
class DeviceControlConnections(RealtimeItem):
    api_path = ApiPath('device/control/connections', None, None, None)
    fields_std = ('system_ip', 'site_id', 'peer_type', 'local_color', 'remote_color', 'state')
    fields_ext = ('private_ip', 'private_port', 'public_ip', 'public_port', 'instance', 'protocol', 'domain_id')


@op_register('control', 'local-properties', 'Control local-properties')
class DeviceControlLocalProperties(RealtimeItem):
    api_path = ApiPath('device/control/localproperties', None, None, None)
    fields_std = ('system_ip', 'site_id', 'device_type', 'organization_name', 'domain_id', 'port_hopped')
    fields_ext = ('protocol', 'tls_port', 'certificate_status', 'root_ca_chain_status', 'certificate_validity',
                  'certificate_not_valid_after')


@op_register('orchestrator', 'connections', 'Orchestrator connections')
class OrchestratorConnections(RealtimeItem):
    api_path = ApiPath('device/orchestrator/connections', None, None, None)
    fields_std = ('system_ip', 'site_id', 'peer_type', 'local_color', 'state')
    fields_ext = ('private_ip', 'private_port', 'public_ip', 'public_port', 'domain_id')


@op_register('orchestrator', 'local-properties', 'Orchestrator local-properties')
class OrchestratorLocalProperties(RealtimeItem):
    api_path = ApiPath('device/orchestrator/localproperties', None, None, None)
    fields_std = ('system_ip', 'device_type', 'organization_name', 'uuid', 'board_serial')
    fields_ext = ('protocol', 'certificate_status', 'root_ca_chain_status', 'certificate_validity',
                  'certificate_not_valid_after')


@op_register('orchestrator', 'valid-vedges', 'Orchestrator valid WAN edges')
class OrchestratorValidEdges(RealtimeItem):
    api_path = ApiPath('device/orchestrator/validvedges', None, None, None)
    fields_std = ('chassis_number', 'serial_number', 'validity')


@op_register('orchestrator', 'valid-vsmarts', 'Orchestrator valid vSmarts')
class OrchestratorValidVsmarts(RealtimeItem):
    api_path = ApiPath('device/orchestrator/validvsmarts', None, None, None)
    fields_std = ('serial_number', )


@op_register('interface', 'info', 'Interface info')
class InterfaceIpv4(RealtimeItem):
    api_path = ApiPath('device/interface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'af_type', 'ip_address', 'ipv6_address', 'if_admin_status', 'if_oper_status',
                  'desc')
    fields_ext = ('tx_drops', 'rx_drops', 'tx_kbps', 'rx_kbps')


@op_register('app-route', 'stats', 'Application-aware route statistics')
class AppRouteStats(RealtimeItem):
    api_path = ApiPath('device/app-route/statistics', None, None, None)
    fields_std = ('index', 'remote_system_ip', 'local_color', 'remote_color', 'total_packets', 'loss',
                  'average_latency', 'average_jitter')
    fields_ext = ('mean_loss', 'mean_latency', 'mean_jitter', 'sla_class_index')


@op_register('app-route', 'sla-class', 'Application-aware SLA class')
class AppRouteSlaClass(RealtimeItem):
    api_path = ApiPath('device/app-route/sla-class', None, None, None)
    fields_std = ('name', 'loss', 'latency', 'jitter')
    fields_ext = ('index',)


@op_register('omp', 'summary', 'OMP summary')
class DeviceOmpSummary(RealtimeItem):
    api_path = ApiPath('device/omp/summary', None, None, None)
    fields_std = ('operstate', 'ompuptime', 'vsmart_peers', 'routes_received', 'routes_installed', 'routes_sent',
                  'tlocs_received', 'tlocs_installed', 'tlocs_sent')
    fields_ext = ('services_received', 'services_installed', 'services_sent', 'policy_received', 'policy_sent')


@op_register('omp', 'peers', 'OMP peers')
class DeviceOmpPeers(RealtimeItem):
    api_path = ApiPath('device/omp/peers', None, None, None)
    fields_std = ('peer', 'type', 'site_id', 'state')
    fields_ext = ('domain_id', 'up_time')


@op_register('omp', 'adv-routes', 'OMP advertised routes')
class DeviceOmpRoutesAdv(RealtimeItem):
    api_path = ApiPath('device/omp/routes/advertised', None, None, None)
    fields_std = ('vpn_id', 'prefix', 'to_peer', 'color', 'ip', 'protocol', 'metric', 'preference')
    fields_ext = ('tag', 'originator', 'site_id')


@op_register('tunnel', 'stats', 'Tunnel statistics')
class DeviceTunnelStats(RealtimeItem):
    api_path = ApiPath('device/tunnel/statistics', None, None, None)
    fields_std = ('system_ip', 'local_color', 'remote_color', 'tunnel_protocol', 'tunnel_mtu', 'tcp_mss_adjust')
    fields_ext = ('source_ip', 'dest_ip', 'source_port', 'dest_port')


@op_register('software', 'info', 'Software info')
class DeviceSoftware(RealtimeItem):
    api_path = ApiPath('device/software', None, None, None)
    fields_std = ('version', 'active', 'default')
    fields_ext = ('confirmed',)


@op_register('dpi', 'summary', 'DPI summary')
class DeviceDpiSummary(RealtimeItem):
    api_path = ApiPath('device/dpi/summary', None, None, None)
    fields_std = ('status', 'current_flows', 'peak_flows', 'current_rate', 'peak_rate')
    fields_ext = ('flows_created', 'flows_expired')


@op_register('arp', 'vedge', 'vEdge ARP table')
class ArpVedge(RealtimeItem):
    api_path = ApiPath('device/arp', None, None, None)
    fields_std = ('vpn_id', 'if_name', 'ip', 'mac', 'state')

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        return device_model not in CEDGE_SET


@op_register('arp', 'cedge', 'cEdge ARP table')
class ArpCedge(RealtimeItem):
    api_path = ApiPath('device/arp', None, None, None)
    fields_std = ('vpn_id', 'interface', 'address', 'hardware', 'mode')

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        return device_model in CEDGE_SET


@op_register('hardware', 'inventory', 'hardware inventory')
class HardwareInventory(RealtimeItem):
    api_path = ApiPath('device/hardware/inventory', None, None, None)
    fields_std = ('hw_type', 'hw_description')
    fields_ext = ('version', 'part_number', 'serial_number')


@op_register('hardware', 'environment', 'hardware environment')
class HardwareEnvironment(RealtimeItem):
    api_path = ApiPath('device/hardware/environment', None, None, None)
    fields_std = ('name', 'sensor_name', 'state')
    fields_ext = ('current_reading', 'sensor_units')

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        return device_model not in SOFT_EDGE_SET


#
# Bulk Statistics Items
#
@op_register('app-route', 'stats', 'Application-aware route statistics')
class BulkAppRoute(BulkStatsItem):
    api_path = ApiPath('data/device/statistics/approutestatsstatistics', None, None, None)
    fields_std = ('local_system_ip', 'remote_system_ip', 'local_color', 'remote_color', 'total', 'loss', 'latency',
                  'jitter', 'name')
    fields_ext = ('tx_pkts', 'rx_pkts', 'tx_octets', 'rx_octets')
    fields_to_avg = ('total', 'loss', 'latency', 'jitter')

    @staticmethod
    def time_series_key(sample: namedtuple) -> str:
        return sample.name


@op_register('interface', 'info', 'Interface info')
class BulkInterfaceStats(BulkStatsItem):
    api_path = ApiPath('data/device/statistics/interfacestatistics', None, None, None)
    fields_std = ('vpn_id', 'interface', 'tx_kbps', 'rx_kbps', 'tx_pps', 'rx_pps')
    fields_ext = ('rx_pkts', 'tx_pkts', 'rx_drops', 'tx_drops', 'rx_errors', 'tx_errors')
    fields_to_avg = ('tx_kbps', 'rx_kbps', 'tx_pps', 'rx_pps')

    @staticmethod
    def time_series_key(sample: namedtuple) -> str:
        return f"{sample.vdevice_name}_{sample.vpn_id}_{sample.interface}"


@op_register('system', 'status', 'System status')
class BulkSystemStats(BulkStatsItem):
    api_path = ApiPath('data/device/statistics/devicesystemstatusstatistics', None, None, None)
    fields_std = ('cpu_user', 'cpu_system', 'mem_util')
    fields_ext = ('mem_used', 'mem_free', 'disk_used', 'disk_avail')
    fields_to_avg = ('cpu_user', 'cpu_system', 'mem_util', 'mem_used', 'mem_free', 'disk_used', 'disk_avail')
    field_conversion_fns = {
        'cpu_system': abs,
        'mem_util': lambda x: 100 * x
    }


#
# Bulk State Items
#
@op_register('system', 'info', 'System info')
class BulkSystemStatus(BulkStateItem):
    api_path = ApiPath('data/device/state/SystemStatus', None, None, None)
    fields_std = ('state', 'total_cpu_count', 'fp_cpu_count', 'linux_cpu_count', 'tcpd_cpu_count')
    fields_ext = ('reboot_reason', 'reboot_type')


@op_register('bfd', 'sessions', 'BFD sessions')
class BulkBfdSessions(BulkStateItem):
    api_path = ApiPath('data/device/state/BFDSessions', None, None, None)
    fields_std = ('system_ip', 'site_id', 'local_color', 'color', 'state')
    fields_ext = ('src_ip', 'src_port', 'dst_ip', 'dst_port', 'transitions', 'uptime_date')


@op_register('control', 'connections', 'Control connections')
class BulkControlConnections(BulkStateItem):
    api_path = ApiPath('data/device/state/ControlConnection', None, None, None)
    fields_std = ('system_ip', 'site_id', 'peer_type', 'local_color', 'remote_color', 'state')
    fields_ext = ('private_ip', 'private_port', 'public_ip', 'public_port', 'instance', 'protocol', 'domain_id',
                  'uptime_date')


@op_register('control', 'local-properties', 'Control local-properties')
class BulkControlLocalProperties(BulkStateItem):
    api_path = ApiPath('data/device/state/ControlLocalProperty', None, None, None)
    fields_std = ('system_ip', 'site_id', 'device_type', 'organization_name', 'domain_id', 'port_hopped')
    fields_ext = ('protocol', 'tls_port', 'certificate_status', 'root_ca_chain_status', 'certificate_validity',
                  'certificate_not_valid_after')


@op_register('interface', 'vedge', 'vEdge interfaces')
class BulkInterfaceVedge(BulkStateItem):
    api_path = ApiPath('data/device/state/Interface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'af_type', 'ip_address', 'ipv6_address', 'if_admin_status',
                  'if_oper_status', 'desc')
    fields_ext = ('mtu', 'hwaddr', 'speed_mbps', 'port_type')


@op_register('interface', 'cedge', 'cEdge interfaces')
class BulkInterfaceCedge(BulkStateItem):
    api_path = ApiPath('data/device/state/CEdgeInterface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'ip_address', 'ipv4_subnet_mask', 'ipv6_addrs', 'if_admin_status',
                  'if_oper_status', 'description')
    fields_ext = ('mtu', 'hwaddr', 'speed_mbps')


@op_register('omp', 'peers', 'OMP peers')
class BulkOmpPeers(BulkStateItem):
    api_path = ApiPath('data/device/state/OMPPeer', None, None, None)
    fields_std = ('peer', 'type', 'site_id', 'state')
    fields_ext = ('domain_id',)
