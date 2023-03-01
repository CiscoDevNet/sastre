"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.base.models_vmanage
 This module implements vManage API models
"""
import re
from typing import Iterable, Set, Optional, Sequence, Mapping, List, Any, Callable, Tuple, Dict, Union
from pathlib import Path
from collections import namedtuple
from copy import deepcopy
from urllib.parse import quote_plus
from pydantic import Field
from .rest_api import Rest, RestAPIException
from .catalog import register, op_register
from .models_base import (ApiItem, IndexApiItem, ConfigItem, Config2Item, IndexConfigItem, RecordItem, RealtimeItem,
                          BulkStatsItem, BulkStateItem, ApiPath, PathKey, CliOrFeatureApiPath, ApiPathGroup, IdName,
                          entry_time_parse, ConfigRequestModel, FeatureProfile, FeatureProfileIndex, AdminSettingsItem)


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
        @param template_input_iter: An iterable of (<template_id>, <input_list>) tuples. Input_list is a list where
                                    each entry represents one attached device and is a dictionary of input
                                    variable names and values.
        @param is_edited: True if this is an in-place re-attach, False if this is a template attach.
        @return: Dictionary used to provide POST input parameters
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
            return f"{task_entry.get('host-name', '<unknown>')}: {', '.join(task_entry.get('activity', []))}"

        data_list = self.data.get('data', [])
        # When action validation fails, returned data is empty
        if len(data_list) == 0:
            validation_details = self.data.get('validation', {}).get('activity', [])
            return ', '.join(validation_details) or 'No further details provided in received action status'

        return ', '.join(device_details(entry) for entry in data_list)


class CheckVBond(ApiItem):
    api_path = ApiPath('template/device/config/vbond', None, None, None)

    @property
    def is_configured(self):
        return self.data.get('isVbondConfigured', False)


class DeviceBootstrap(ApiItem):
    api_path = ApiPath('system/device/bootstrap/device/{uuid}', None, None, None)

    @property
    def uuid(self) -> str:
        return self.parse(r'- uuid : ([^$]+?)$')

    @property
    def otp(self) -> str:
        return self.parse(r'- otp : ([^$]+?)$')

    @property
    def vbond(self) -> str:
        return self.parse(r'- vbond : ([^$]+?)$')

    @property
    def organization(self) -> str:
        return self.parse(r'- org : ([^$]+?)$')

    def parse(self, regex: str) -> str:
        match = re.search(regex, self.data.get('bootstrapConfig', ''), re.MULTILINE)
        if not match:
            raise RestAPIException("Unexpected 'bootstrapConfig' format")

        return match.group(1)

    @property
    def bootstrap_config(self) -> str:
        config = self.data.get('bootstrapConfig')
        if config is None:
            raise RestAPIException("Missing 'bootstrapConfig'")

        return config

    @classmethod
    def get(cls, api: Rest, *, uuid: Optional[str] = None,
            config_type: str = 'cloudinit', include_default_root_certs: bool = True, version: str = 'v1'):

        if uuid is None:
            raise ValueError("Parameter 'uuid' is required")

        return super().get(
            api, uuid=uuid, configtype=config_type, inclDefRootCert=include_default_root_certs, version=version
        )


#
# Device Inventory
#
class Device(IndexApiItem):
    api_path = ApiPath('device', None, None, None)
    iter_fields = ('uuid', 'host-name')

    extended_iter_fields = ('deviceId', 'site-id', 'reachability', 'device-type', 'device-model')


class Inventory(IndexApiItem):
    """
    Parent class for the inventory-type classes EdgeInventory and ControlInventory.
    Not supposed to be used directly, use the corresponding child classes instead.
    """
    FilterEntry = namedtuple('InventoryFilterEntry', ['uuid', 'cert_state', 'name', 'system_ip',
                                                      'model', 'type', 'template', 'config_group'])

    @staticmethod
    def is_cedge(device_entry: FilterEntry) -> bool:
        """
        Filtered_iter filter selecting CEDGE devices
        """
        return device_entry.model is not None and device_entry.model in CEDGE_SET

    @staticmethod
    def is_vsmart(device_entry: FilterEntry) -> bool:
        return device_entry.type is not None and device_entry.type == 'vsmart'

    @staticmethod
    def is_vbond(device_entry: FilterEntry) -> bool:
        return device_entry.type is not None and device_entry.type == 'vbond'

    @staticmethod
    def is_vmanage(device_entry: FilterEntry) -> bool:
        return device_entry.type is not None and device_entry.type == 'vmanage'

    @staticmethod
    def is_available(device_entry: FilterEntry) -> bool:
        """
        Filtered_iter filter selecting devices available, that is, not yet attached to a template or config-group
        """
        return not device_entry.template and not device_entry.config_group

    @staticmethod
    def is_attached(device_entry: FilterEntry) -> bool:
        """
        Filtered_iter filter selecting devices currently attached to a template
        """
        return device_entry.template is not None and len(device_entry.template) > 0

    @staticmethod
    def is_associated(device_entry: FilterEntry) -> bool:
        """
        Filtered_iter filter selecting devices currently associated with a config-group
        """
        return device_entry.config_group is not None and len(device_entry.config_group) > 0

    def filtered_iter(self, *filter_fns: Callable) -> Iterable[FilterEntry]:
        # If no filter_fns is provided, no filtering is done and iterate over all entries
        return (
            entry for entry
            in map(Inventory.FilterEntry._make, self.iter(*self.iter_fields, *self.extended_iter_fields,
                                                          'deviceModel', 'deviceType', 'template', 'name'))
            if all(filter_fn(entry) for filter_fn in filter_fns)
        )


class EdgeInventory(Inventory):
    api_path = ApiPath('system/device/vedges', None, None, None)
    iter_fields = ('uuid', 'vedgeCertificateState')
    extended_iter_fields = ('host-name', 'system-ip')

    @staticmethod
    def is_cert_installed(device_entry: Inventory.FilterEntry) -> bool:
        """
        Filtered_iter filter selecting devices with certificate installed
        """
        return device_entry.cert_state is not None and device_entry.cert_state == 'certinstalled'


class ControlInventory(Inventory):
    api_path = ApiPath('system/device/controllers', None, None, None)
    iter_fields = ('uuid', 'validity')
    extended_iter_fields = ('host-name', 'system-ip')

    @staticmethod
    def is_cert_valid(device_entry: Inventory.FilterEntry) -> bool:
        """
        Filtered_iter filter selecting devices with certificate installed
        """
        return device_entry.cert_state is not None and device_entry.cert_state == 'valid'


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

        @param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        @param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        @param item_name: (Optional) Name of the item being saved. Variable used to build the filename.
        @param item_id: (Optional) UUID for the item being saved. Variable used to build the filename.
        @return: True indicates data has been saved. False indicates no data to save (and no file has been created).
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
# Set of device types that use cedge template class. Updated as of vManage 20.10.0
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
    "vedge-nfvis-C8200-UCPEVM", "vedge-IR-8340", "cellular-gateway-CG522MW-IO-GL", "vedge-IR-8140H", "vedge-C1131X-8PW",
    "vedge-IR-8140H-P", "vedge-C1131-8PLTEPW", "vedge-C1131-8PW", "vedge-C1131X-8PLTEPW", "cellular-gateway-CG113-W6Z",
    "cellular-gateway-CG113-W6B", "cellular-gateway-CG113-W6A", "cellular-gateway-CG113-4GW6E",
    "cellular-gateway-CG113-4GW6H", "vedge-C8500-20X6C", "cellular-gateway-CG113-W6E",  "cellular-gateway-CG113-W6H",
    "cellular-gateway-CG113-4GW6B", "cellular-gateway-CG113-4GW6Z", "cellular-gateway-CG113-4GW6A",
    "cellular-gateway-CG113-4GW6Q", "cellular-gateway-CG113-W6Q", "cellular-gateway-CG522MW-IO-NA",
    "vedge-ESR-6300-NCP", "vedge-nfvis-CSP-5436", "vedge-nfvis-CSP-5228", "vedge-nfvis-CSP-5216"
}
# Software devices. Updated as of vManage 20.10.0
SOFT_EDGE_SET = {"vedge-CSR-1000v", "vedge-C8000V", "vedge-cloud", "vmanage", "vsmart"}


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
    def api_params(template_id: str, device_uuids: Iterable[str]) -> dict:
        """
        Build dictionary used to provide input parameters for api POST call
        @param template_id: Template ID string
        @param device_uuids: Iterable of device UUIDs
        @return: Dictionary used to provide POST input parameters
        """
        return {
            "deviceIds": list(device_uuids),
            "isEdited": False,
            "isMasterEdited": False,
            "templateId": template_id
        }

    def input_list(self, allowed_uuid_set=None):
        """
        Return list of device input entries. Each entry represents one attached device and is a dictionary of input
        variable names and values.
        @param allowed_uuid_set: Optional, set of uuids. If provided, only input entries for those uuids are returned
        @return: [{<input_var_name>: <input_var_value>, ...}, ...]
        """
        return [entry for entry in self.data.get('data', [])
                if allowed_uuid_set is None or entry.get('csv-deviceId') in allowed_uuid_set]

    @staticmethod
    def input_list_devices(input_list: list) -> Iterable[str]:
        return (entry.get('csv-host-name') for entry in input_list)

    def values_iter(self):
        return (
            (entry.get('csv-deviceId', ''), entry.get('csv-host-name', ''), entry)
            for entry in self.data.get('data', [])
        )

    def title_dict(self):
        return {column['property']: column['title'] for column in self.data.get('header', {}).get('columns', [])}

    def __iter__(self):
        return self.values_iter()

    @classmethod
    def get_values(cls, api: Rest, template_id: str, device_uuids: Iterable[str]):
        try:
            return cls(api.post(cls.api_params(template_id, device_uuids), cls.api_path.post))
        except RestAPIException:
            return None


class DeviceTemplate(ConfigItem):
    api_path = CliOrFeatureApiPath(
        ApiPath('template/device/object', 'template/device/feature', 'template/device'),
        ApiPath('template/device/object', 'template/device/cli', 'template/device')
    )
    store_path = ('device_templates', 'template')
    store_file = '{item_name}.json'
    name_tag = 'templateName'
    id_tag = 'templateId'
    post_filtered_tags = ('feature',)
    # templateClass, deviceRole, draftMode, templateId and copyEdited are new tags in 20.x+, adding to skip diff to not
    # trigger updates when restore --update is done between pre 20.x workdir and post 20.x vManage.
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'templateAttached', 'templateConfigurationEdited', 'templateClass', 'deviceRole', 'draftMode',
                        'templateId', 'copyEdited'}

    def __init__(self, data):
        """
        @param data: dict containing the information to be associated with this config item
        """
        super().__init__(data)

        self.devices_attached: Optional[DeviceTemplateAttached] = None
        self.attach_values: Optional[DeviceTemplateValues] = None

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

    FilteredIterEntry = namedtuple('FilteredIterEntry', ['device_type', 'num_attached', 'uuid', 'name'])

    @staticmethod
    def is_vsmart(iterator_entry: FilteredIterEntry) -> bool:
        return iterator_entry.device_type is not None and iterator_entry.device_type == 'vsmart'

    @staticmethod
    def is_not_vsmart(iterator_entry: FilteredIterEntry) -> bool:
        return iterator_entry.device_type is not None and iterator_entry.device_type != 'vsmart'

    @staticmethod
    def is_attached(iterator_entry: FilteredIterEntry) -> bool:
        return iterator_entry.num_attached is not None and iterator_entry.num_attached > 0

    @staticmethod
    def is_cedge(iterator_entry: FilteredIterEntry) -> bool:
        return iterator_entry.device_type is not None and iterator_entry.device_type in CEDGE_SET

    def filtered_iter(self, *filter_fns: Callable) -> Iterable[Tuple[str, str]]:
        # The contract for filtered_iter is that it should return an iterable of iter_fields tuples.
        # If no filter_fns is provided, no filtering is done and iterate over all entries
        return (
            (entry.uuid, entry.name) for entry in map(DeviceTemplateIndex.FilteredIterEntry._make,
                                                      self.iter('deviceType', 'devicesAttached', *self.iter_fields))
            if all(filter_fn(entry) for filter_fn in filter_fns)
        )

    @classmethod
    def create(cls, item_list: Sequence[DeviceTemplate], id_hint_dict: Mapping[str, str]):
        def index_entry_dict(item_obj: DeviceTemplate):
            entry_dict = {
                key: item_obj.data.get(key, id_hint_dict.get(item_obj.name)) for key in cls.iter_fields
            }
            entry_dict['deviceType'] = item_obj.data.get('deviceType')

            if item_obj.devices_attached is not None:
                entry_dict['devicesAttached'] = len(list(item_obj.devices_attached))
            else:
                entry_dict['devicesAttached'] = 0

            return entry_dict

        index_payload = {
            'data': [index_entry_dict(item) for item in item_list]
        }
        return cls(index_payload)


class FeatureTemplate(ConfigItem):
    api_path = ApiPath('template/feature/object', 'template/feature')
    store_path = ('feature_templates',)
    store_file = '{item_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'
    type_tag = 'templateType'
    # gTemplateClass is new in 20.x, adding skip diff to not trigger updates when restore --update is done between
    # pre 20.x workdir and post 20.x vManage.
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'devicesAttached', 'attachedMastersCount', 'gTemplateClass'}

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


#
# Config Group
#

class ConfigGroupProfileModel(ConfigRequestModel):
    id: str


class ConfigGroupModel(ConfigRequestModel):
    name: str
    description: str
    solution: str
    profiles: Optional[List[ConfigGroupProfileModel]] = None


class ConfigGroup(Config2Item):
    api_path = ApiPath('v1/config-group')
    store_path = ('config_groups', 'group')
    store_file = '{item_name}.json'
    id_tag = 'id'
    name_tag = 'name'

    post_model = ConfigGroupModel

    @property
    def devices_associated(self) -> int:
        return len(self.data.get('devices', []))


@register('config_group', 'configuration group', ConfigGroup, min_version='20.8')
class ConfigGroupIndex(IndexConfigItem):
    api_path = ApiPath('v1/config-group', None, None, None)
    store_file = 'config_groups.json'
    iter_fields = IdName('id', 'name')


class NameValuePair(ConfigRequestModel):
    name: str
    value: Any


class DeviceValuesModel(ConfigRequestModel):
    device_id: str = Field(..., alias='device-id')
    variables: List[NameValuePair]


class ConfigGroupValuesModel(ConfigRequestModel):
    solution: str
    devices: List[DeviceValuesModel]

    # In 20.8.1 get values contains 'family' key while put request requires 'solution' instead
    def __init__(self, **kwargs):
        solution = kwargs.pop('solution', None) or kwargs.pop('family', None)
        if solution is not None:
            kwargs['solution'] = solution
        super().__init__(**kwargs)


class ConfigGroupValues(Config2Item):
    api_path = ApiPath('v1/config-group/{configGroupId}/device/variables', None,
                       'v1/config-group/{configGroupId}/device/variables', None)
    store_path = ('config_groups', 'values')
    store_file = '{item_name}.json'

    post_model = ConfigGroupValuesModel

    @property
    def uuids(self) -> Iterable[str]:
        return (entry['device-id'] for entry in self.data.get('devices', []) if 'device-id' in entry)

    @property
    def is_empty(self) -> bool:
        return self.data is None or len(self.data.get('devices', [])) == 0

    def filter(self, allowed_uuid_set: Set[str]) -> 'ConfigGroupValues':
        """
        Return a new instance of ConfigGroupValues containing only device entries with an id that is present in
        allowed_uuid_set.
        @param allowed_uuid_set: Set of device uuids that are allowed
        @return: Filtered ConfigGroupValues instance
        """
        new_payload = deepcopy(self.data)
        new_payload['devices'] = [
            entry for entry in new_payload.get('devices', []) if entry.get('device-id') in allowed_uuid_set
        ]
        return ConfigGroupValues(new_payload)

    def put_raise(self, api: Rest, **path_vars: str) -> Sequence[str]:
        result = api.put(self.put_data(), ConfigGroupValues.api_path.resolve(**path_vars).put)

        return [entry.get('device-id') for entry in result]


class AssociatedDeviceModel(ConfigRequestModel):
    id: str


class ConfigGroupAssociatedModel(ConfigRequestModel):
    devices: List[AssociatedDeviceModel]


class ConfigGroupAssociated(Config2Item):
    api_path = ApiPath('v1/config-group/{configGroupId}/device/associate')
    store_path = ('config_groups', 'associated')
    store_file = '{item_name}.json'

    post_model = ConfigGroupAssociatedModel

    ActionWorker = namedtuple('ActionWorker', ['uuid', ])

    @property
    def uuids(self) -> Iterable[str]:
        return (entry['id'] for entry in self.data.get('devices', []) if 'id' in entry)

    @property
    def is_empty(self) -> bool:
        return self.data is None or len(self.data.get('devices', [])) == 0

    def filter(self, allowed_uuid_set: Optional[Set[str]] = None, not_by_rule: bool = False) -> 'ConfigGroupAssociated':
        """
        Return a new instance of ConfigGroupAssociated containing only device entries with an id that is present in
        allowed_uuid_set.
        @param allowed_uuid_set: Set of device uuids that are allowed. If not provided, do not filter by uuid.
        @param not_by_rule: If True, only include devices that were not added by tag rules.
        @return: Filtered ConfigGroupAssociated instance
        """
        new_payload = deepcopy(self.data)
        new_payload['devices'] = [
            entry for entry in new_payload.get('devices', [])
            if (
                (allowed_uuid_set is None or entry.get('id') in allowed_uuid_set) and
                (not not_by_rule or not entry.get('addedByRule', False))
            )
        ]
        return ConfigGroupAssociated(new_payload)

    def put_raise(self, api: Rest, **path_vars: str) -> None:
        api.put(self.put_data(), ConfigGroupAssociated.api_path.resolve(**path_vars).put)

        return

    @staticmethod
    def delete_raise(api: Rest, uuids: Iterable[str], **path_vars: str) -> ActionWorker:
        payload = {
            "devices": [
                {"id": device_id} for device_id in uuids
            ]
        }
        response = api.delete(ConfigGroupAssociated.api_path.resolve(**path_vars).delete, input_data=payload)

        return ConfigGroupAssociated.ActionWorker(uuid=response.get('parentTaskId'))


class ConfigGroupRules(IndexConfigItem):
    api_path = ApiPath('tag/tagRules/{configGroupId}', 'tag/tagRules')
    store_path = ('config_groups', 'tag_rules')
    store_file = '{item_name}.json'
    id_tag = 'tagId'
    iter_fields = ('tagId', )

    @staticmethod
    def delete_raise(api: Rest, config_group_id: str, rule_id: str) -> None:
        # 'tag/tagRules/{tag_rule_id}?configGroupId={config_group_id}'
        api.delete(ConfigGroupRules.api_path.resolve(configGroupId=config_group_id).delete, rule_id,
                   configGroupId=config_group_id)

    def post_raise(self, api: Rest, config_group_id: str) -> List[str]:
        filtered_keys = {
            self.id_tag,
        }
        response_list = []
        for rule in self.data:
            post_data = {k: v for k, v in rule.items() if k not in filtered_keys}
            post_data['configGroupId'] = config_group_id
            response = api.post(post_data, ConfigGroupRules.api_path.resolve(configGroupId=config_group_id).post)
            response_list.extend(
                entry.get('chassisNumber') for entry in response.get('devices', {}).get('matchingDevices', [])
            )

        return response_list


class ConfigGroupDeploy(ApiItem):
    api_path = ApiPath(None, 'v1/config-group/{configGroupId}/device/deploy', None, None)
    id_tag = 'parentTaskId'

    @staticmethod
    def api_params(uuids: Iterable[str]) -> Dict[str, Any]:
        """
        Build dictionary used to provide input parameters for api POST call
        @param uuids: An iterable of device UUIDs to deploy
        @return: Dictionary used to provide POST input parameters
        """
        return {
            "devices": [
                {"id": device_id} for device_id in uuids
            ]
        }


#
# Feature Profiles
#

class ProfileSdwanSystem(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/system')
    store_path = ('feature_profiles', 'sdwan', 'system')
    parcel_api_paths = ApiPathGroup({
        "aaa": ApiPath("v1/feature-profile/sdwan/system/{systemId}/aaa"),
        "global": ApiPath("v1/feature-profile/sdwan/system/{systemId}/global"),
        "banner": ApiPath("v1/feature-profile/sdwan/system/{systemId}/banner"),
        "basic": ApiPath("v1/feature-profile/sdwan/system/{systemId}/basic"),
        "bfd": ApiPath("v1/feature-profile/sdwan/system/{systemId}/bfd"),
        "logging": ApiPath("v1/feature-profile/sdwan/system/{systemId}/logging"),
        "ntp": ApiPath("v1/feature-profile/sdwan/system/{systemId}/ntp"),
        "omp": ApiPath("v1/feature-profile/sdwan/system/{systemId}/omp"),
        "snmp": ApiPath("v1/feature-profile/sdwan/system/{systemId}/snmp"),
        "perfmonitor": ApiPath("v1/feature-profile/sdwan/system/{systemId}/perfmonitor")
     })


@register('feature_profile', 'SDWAN system profile', ProfileSdwanSystem, min_version='20.8')
class ProfileSdwanSystemIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/system', None, None, None)
    store_file = 'feature_profiles_sdwan_system.json'


class ProfileSdwanService(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/service')
    store_path = ('feature_profiles', 'sdwan', 'service')
    parcel_api_paths = ApiPathGroup({
        "dhcp-server": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/dhcp-server"),
        "routing/bgp": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/routing/bgp"),
        "routing/ospf": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/routing/ospf"),
        "lan/vpn": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/lan/vpn"),
        "lan/vpn/interface/ethernet": ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/ethernet"),
        "lan/vpn/interface/svi": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/svi"),
        "lan/vpn/interface/ipsec": ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/ipsec"),
        "switchport": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/switchport"),
        "wirelesslan": ApiPath("v1/feature-profile/sdwan/service/{serviceId}/wirelesslan")
    }, parcel_reference_path_map={
        PathKey("dhcp-server", "lan/vpn/interface/ethernet"): ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/ethernet/{ethId}/dhcp-server"),
        PathKey("dhcp-server", "lan/vpn/interface/svi"): ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/svi/{sviId}/dhcp-server"),
        PathKey("dhcp-server", "lan/vpn/interface/ipsec"): ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/interface/ipsec/{ipsecId}/dhcp-server"),
        PathKey("routing/bgp", "lan/vpn"): ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/routing/bgp"),
        PathKey("routing/ospf", "lan/vpn"): ApiPath(
            "v1/feature-profile/sdwan/service/{serviceId}/lan/vpn/{vpnId}/routing/ospf"),
    })


@register('feature_profile', 'SDWAN service profile', ProfileSdwanService, min_version='20.8')
class ProfileSdwanServiceIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/service', None, None, None)
    store_file = 'feature_profiles_sdwan_service.json'


class ProfileSdwanTransport(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/transport')
    store_path = ('feature_profiles', 'sdwan', 'transport')
    parcel_api_paths = ApiPathGroup({
        "routing/bgp": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/routing/bgp"),
        "tracker": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/tracker"),
        "cellular-profile": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/cellular-profile"),
        "wan/vpn": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/wan/vpn"),
        "wan/vpn/interface/ethernet": ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/ethernet"),
        "wan/vpn/interface/ipsec": ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/ipsec"),
        "wan/vpn/interface/cellular": ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/cellular"),
        "management/vpn": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/management/vpn"),
        "management/vpn/interface/ethernet": ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/management/vpn/{vpnId}/interface/ethernet"),
        "cellular-controller": ApiPath("v1/feature-profile/sdwan/transport/{transportId}/cellular-controller"),
    }, parcel_reference_path_map={
        PathKey("routing/bgp", "wan/vpn"): ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/routing/bgp"),
        PathKey("tracker", "wan/vpn/interface/ethernet"): ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/ethernet/{ethernetId}/tracker"),
        PathKey("tracker", "wan/vpn/interface/ipsec"): ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/ipsec/{ipsecId}/tracker"),
        PathKey("tracker", "wan/vpn/interface/cellular"): ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/wan/vpn/{vpnId}/interface/cellular/{cellularId}/tracker"),
        PathKey("cellular-profile", "cellular-controller"): ApiPath(
            "v1/feature-profile/sdwan/transport/{transportId}/cellular-controller/"
            "{cellularControllerId}/cellular-profile"),
    })


@register('feature_profile', 'SDWAN transport profile', ProfileSdwanTransport, min_version='20.8')
class ProfileSdwanTransportIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/transport', None, None, None)
    store_file = 'feature_profiles_sdwan_transport.json'


class ProfileSdwanCli(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/cli')
    store_path = ('feature_profiles', 'sdwan', 'cli')
    parcel_api_paths = ApiPathGroup({
        "config": ApiPath("v1/feature-profile/sdwan/cli/{cliId}/config")
    })


@register('feature_profile', 'SDWAN CLI profile', ProfileSdwanCli, min_version='20.8')
class ProfileSdwanCliIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/cli', None, None, None)
    store_file = 'feature_profiles_sdwan_cli.json'


class ProfileSdwanOther(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/other')
    store_path = ('feature_profiles', 'sdwan', 'other')
    parcel_api_paths = ApiPathGroup({
        "thousandeyes": ApiPath("v1/feature-profile/sdwan/other/{otherId}/thousandeyes")
    })


@register('feature_profile', 'SDWAN other profile', ProfileSdwanOther, min_version='20.9')
class ProfileSdwanOtherIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/other', None, None, None)
    store_file = 'feature_profiles_sdwan_other.json'


# Policy-object profiles show up in 20.10, but there is no documentation in the apidocs
class ProfileSdwanPolicy(FeatureProfile):
    api_path = ApiPath('v1/feature-profile/sdwan/policy-object')
    store_path = ('feature_profiles', 'sdwan', 'policy_object')
    parcel_api_paths = ApiPathGroup({
        "as-path": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/as-path"),
        "class": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/class"),
        "standard-community": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/standard-community"),
        "expanded-community": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/expanded-community"),
        "data-prefix": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/data-prefix"),
        "data-ipv6-prefix": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/data-ipv6-prefix"),
        "ipv6-prefix": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/ipv6-prefix"),
        "prefix": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/prefix"),
        "ext-community": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/ext-community"),
        "mirror": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/mirror"),
        "policer": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/policer"),
        "vpn-group": ApiPath("v1/feature-profile/sdwan/policy-object/{policyId}/vpn-group")
    })


@register('feature_profile', 'SDWAN policy object', ProfileSdwanPolicy, min_version='20.10')
class ProfileSdwanPolicyIndex(FeatureProfileIndex):
    api_path = ApiPath('v1/feature-profile/sdwan/policy-object', None, None, None)
    store_file = 'feature_profiles_sdwan_policy_object.json'


# Those profiles show in 20.10 GUI but don't have any entry in apidocs. DE indicated to hold off on those as they'll
# have major changes. Plan to include in 20.12
# class ProfileSdwanSecurity(FeatureProfile):
#     api_path = ApiPath('v1/feature-profile/sdwan/security')
#     store_path = ('feature_profiles', 'sdwan', 'security')
#     parcel_api_paths = ApiPathGroup({
#         "sig": ApiPath("v1/feature-profile/sdwan/security/{securityId}/sig")
#     })
#
#
# @register('feature_profile', 'SDWAN security profile', ProfileSdwanSecurity, min_version='20.10')
# class ProfileSdwanSecurityIndex(FeatureProfileIndex):
#     api_path = ApiPath('v1/feature-profile/sdwan/security', None, None, None)
#     store_file = 'feature_profiles_sdwan_security.json'
#
#
# class ProfileSdwanPolicy(FeatureProfile):
#     api_path = ApiPath('v1/feature-profile/sdwan/policy-object')
#     store_path = ('feature_profiles', 'sdwan', 'policy')
#     parcel_api_paths = ApiPathGroup({
#         "sig": ApiPath("v1/feature-profile/sdwan/security/{securityId}/sig")
#     })
#
#
# @register('feature_profile', 'SDWAN policy profile', ProfileSdwanPolicy, min_version='20.10')
# class ProfileSdwanPolicyIndex(FeatureProfileIndex):
#     api_path = ApiPath('v1/feature-profile/sdwan/policy-object', None, None, None)
#     store_file = 'feature_profiles_sdwan_policy.json'


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
        @return: (<id>, <name>) or (None, None)
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
    # policyUseCase, policyMode are new tags in 20.x+, adding to skip diff to not trigger updates when restore --update
    # is done between pre 20.x workdir and post 20.x vManage.
    skip_cmp_tag_set = {'policyUseCase', 'policyMode'}


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
    skip_cmp_tag_set = {'lastUpdated', 'referenceCount', 'references', 'activatedId', 'isActivatedByVsmart', 'owner'}
    post_filtered_tags = ('referenceCount', 'references')

    def __init__(self, data):
        """
        @param data: dict containing the information to be associated with this API item.
        """
        # In 20.3.1 the payload returned by vManage contains a 'data' key with the policy definition in it. This is
        # different from previous versions or other ConfigItems. Overwriting the default __init__ in order to
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
    # mode is new tag in 20.x+, adding to skip diff to not trigger updates when restore --update is done between pre
    # 20.x workdir and post 20.x vManage.
    skip_cmp_tag_set = {'lastUpdated', 'referenceCount', 'references', 'activatedId', 'isActivatedByVsmart',
                        'owner', 'infoTag', 'mode'}


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


class AdvancedInspectionProfile(PolicyDef):
    api_path = ApiPath('template/policy/definition/advancedinspectionprofile')
    store_path = ('policy_definitions', 'AdvancedInspectionProfile')


@register('policy_definition', 'advanced inspection profile policy definition', AdvancedInspectionProfile,
          min_version='20.6')
class AdvancedInspectionProfileIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/advancedinspectionprofile', None, None, None)
    store_file = 'policy_definitions_advancedinspectionprofile.json'


# VPN QoS MAP is registered as a parent_policy_definition because it references other policy definitions (e.g. QoSMAP)
class VpnQosMap(PolicyDef):
    api_path = ApiPath('template/policy/definition/vpnqosmap')
    store_path = ('policy_definitions', 'VpnQosMap')


@register('parent_policy_definition', 'vpn qos map policy definition', VpnQosMap, min_version='20.6')
class VpnQosMapIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/vpnqosmap', None, None, None)
    store_file = 'policy_definitions_vpnqosmap.json'


class SecurityGroup(PolicyDef):
    api_path = ApiPath('template/policy/definition/securitygroup')
    store_path = ('policy_definitions', 'SecurityGroup')


@register('policy_definition', 'security group policy definition', SecurityGroup, min_version='20.6')
class SecurityGroupIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/securitygroup', None, None, None)
    store_file = 'policy_definitions_securitygroup.json'


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


@register('policy_list', 'translation profile', PolicyListTransProfile, min_version='20.1')
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
    api_path = ApiPath('template/policy/list/expandedcommunity')
    store_path = ('policy_lists', 'ExpandedCommunity')


@register('policy_list', 'expanded community list', PolicyListExpandedCommunity, min_version='20.5')
class PolicyListExpandedCommunityIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/expandedcommunity', None, None, None)
    store_file = 'policy_lists_expanded_community.json'


class PolicyListGeoLocation(PolicyList):
    api_path = ApiPath('template/policy/list/geolocation')
    store_path = ('policy_lists', 'GeoLocation')


@register('policy_list', 'geo location list', PolicyListGeoLocation, min_version='20.5')
class PolicyListGeoLocationIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/geolocation', None, None, None)
    store_file = 'policy_lists_geo_location.json'


class PolicyListRegion(PolicyList):
    api_path = ApiPath('template/policy/list/region')
    store_path = ('policy_lists', 'Region')


@register('policy_list', 'region list', PolicyListRegion, min_version='20.7')
class PolicyListRegionIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/region', None, None, None)
    store_file = 'policy_lists_region.json'


class PolicyListPreferredColorGroup(PolicyList):
    api_path = ApiPath('template/policy/list/preferredcolorgroup')
    store_path = ('policy_lists', 'PreferredColorGroup')


@register('policy_list', 'preferred color group list', PolicyListPreferredColorGroup, min_version='20.9')
class PolicyListPreferredColorGroupIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/preferredcolorgroup', None, None, None)
    store_file = 'policy_lists_preferredcolorgroup.json'


class PolicyListIdentity(PolicyList):
    api_path = ApiPath('template/policy/list/identity')
    store_path = ('policy_lists', 'Identity')


@register('policy_list', 'identity list', PolicyListIdentity, min_version='20.10')
class PolicyListIdentityIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/identity', None, None, None)
    store_file = 'policy_lists_identity.json'


class PolicyListScalableGroupTag(PolicyList):
    api_path = ApiPath('template/policy/list/scalablegrouptag')
    store_path = ('policy_lists', 'ScalableGroupTag')


@register('policy_list', 'scalable group tag list', PolicyListScalableGroupTag, min_version='20.10')
class PolicyListScalableGroupTagIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/scalablegrouptag', None, None, None)
    store_file = 'policy_lists_scalable_group_tag.json'


#
# Admin Settings
#
class SettingsVbond(AdminSettingsItem):
    setting = 'device'
    store_file = 'vbond.json'

    @property
    def is_configured(self) -> bool:
        domain_ip = self.data.get('domainIp', '')
        return len(domain_ip) > 0 and domain_ip != 'Not Configured'

    @property
    def domain_ip(self) -> Union[str, None]:
        return self.data['domainIp'] if self.is_configured else None

    @property
    def port(self) -> Union[str, None]:
        return self.data['port'] if self.is_configured else None


class SettingsOrganization(AdminSettingsItem):
    setting = 'organization'
    store_file = 'organization.json'

    @property
    def organization(self) -> Union[str, None]:
        return self.data.get('org')

    @property
    def is_control_up(self) -> bool:
        return self.data.get('controlConnectionUp', False)


class SettingsCertificate(AdminSettingsItem):
    setting = 'certificate'
    store_file = 'certificate.json'

    @property
    def signing(self) -> Union[str, None]:
        return self.data.get('certificateSigning')

    @classmethod
    def set_signing_enterprise(cls, api: Rest, root_ca_certificate: str) -> None:
        api_path = cls.api_path.resolve(setting=cls.setting).post

        enterprise_reply = api.post({"certificateSigning": "enterprise"}, api_path)
        if enterprise_reply.get("data", [{}, ])[0].get("certificateSigning") != "enterprise":
            raise RestAPIException("Unable to set enterprise certificate signing")

        root_ca_reply = api.put({"enterpriseRootCA": root_ca_certificate}, api_path, "enterpriserootca")
        if root_ca_reply.get("data", [{}, ])[0].get("enterpriseRootCA") != root_ca_certificate:
            raise RestAPIException("Unable to set enterprise root CA certificate")


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
        @param state: string containing the WAN edge certificate state field.
        @return: string
        """
        return cls._state_lookup.get(state, state)

    def status_post_data(self, *new_status):
        """
        Build payload to be used for POST requests that update WAN edge certificate validity status
        @param new_status: One or more (<uuid>, <new status>) tuples
        @return: List containing payload for POST requests
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
# Log items
#
def datetime_format(timestamp: Optional[str]) -> str:
    return entry_time_parse(timestamp).strftime("%Y-%m-%d %H:%M:%S %Z") if timestamp is not None else ''


class Alarm(RecordItem):
    api_path = ApiPath(None, 'alarms', None, None)
    fields_std = ('entry_time', 'devices', 'severity', 'type', 'message', 'active')
    fields_ext = ('acknowledged', 'uuid', 'cleared_time')
    field_conversion_fns = {
        'entry_time': datetime_format,
        'cleared_time': datetime_format
    }


class Event(RecordItem):
    api_path = ApiPath(None, 'event', None, None)
    fields_std = ('entry_time', 'host_name', 'severity_level', 'eventname')
    fields_ext = ('details',)
    field_conversion_fns = {
        'entry_time': datetime_format
    }


#
# Realtime items
#
@op_register('system', 'status', 'System status')
class SystemStatus(RealtimeItem):
    api_path = ApiPath('device/system/status', None, None, None)
    fields_std = ('state', 'cpu_user', 'cpu_system', 'mem_total', 'mem_free')
    fields_ext = ('disk_size', 'disk_used')


@op_register('system', 'statistics', 'System statistics')
class SystemStats(RealtimeItem):
    api_path = ApiPath('device/system/statistics', None, None, None)
    fields_std = ('rx_pkts', 'tx_pkts', 'rx_drops', 'fragment_df_drops')
    fields_ext = ('ip_fwd_to_cpu', 'to_cpu_policer_drops')


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
    fields_sub = ('local_color', 'remote_color')


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
    fields_std = ('serial_number',)


@op_register('interface', 'vedge', 'vEdge interface information')
class InterfaceVedge(RealtimeItem):
    api_path = ApiPath('device/interface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'af_type', 'ip_address', 'ipv6_address', 'if_admin_status', 'if_oper_status',
                  'desc')
    fields_ext = ('tx_drops', 'rx_drops', 'tx_kbps', 'rx_kbps')
    fields_sub = ('ifname',)

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        return device_model not in CEDGE_SET


@op_register('interface', 'cedge', 'cEdge interface information')
class InterfaceCedge(RealtimeItem):
    api_path = ApiPath('device/interface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'ip_address', 'if_admin_status', 'if_oper_status')
    fields_ext = ('tx_drops', 'rx_drops', 'tx_kbps', 'rx_kbps')
    fields_sub = ('ifname',)

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        return device_model in CEDGE_SET


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
    fields_std = ('cpu_user_new', 'mem_util')
    fields_ext = ('mem_used', 'mem_free', 'disk_used', 'disk_avail')
    fields_to_avg = ('cpu_user_new', 'mem_util', 'mem_used', 'mem_free', 'disk_used', 'disk_avail')
    field_conversion_fns = {
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
    fields_sub = ('local_color', 'remote_color')


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
    fields_sub = ('ifname',)


@op_register('interface', 'cedge', 'cEdge interfaces')
class BulkInterfaceCedge(BulkStateItem):
    api_path = ApiPath('data/device/state/CEdgeInterface', None, None, None)
    fields_std = ('vpn_id', 'ifname', 'ip_address', 'ipv4_subnet_mask', 'ipv6_addrs', 'if_admin_status',
                  'if_oper_status', 'description')
    fields_ext = ('mtu', 'hwaddr', 'speed_mbps')
    fields_sub = ('ifname',)


@op_register('omp', 'peers', 'OMP peers')
class BulkOmpPeers(BulkStateItem):
    api_path = ApiPath('data/device/state/OMPPeer', None, None, None)
    fields_std = ('peer', 'type', 'site_id', 'state')
    fields_ext = ('domain_id',)
