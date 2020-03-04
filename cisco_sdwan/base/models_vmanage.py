"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.models_vmanage
 This module implements vManage API models
"""
from .catalog import register
from .models_base import ApiItem, IndexApiItem, ConfigItem, IndexConfigItem, ApiPath, IdName


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
            return vsmart_entry['operationMode'] == 'vmanage' and vsmart_entry['isOnline']

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
            return task_entry['status'] == 'Success'

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


#
# Device Inventory
#
class EdgeInventory(IndexApiItem):
    api_path = ApiPath('system/device/vedges', None, None, None)
    iter_fields = ('uuid', 'vedgeCertificateState')


class ControlInventory(IndexApiItem):
    api_path = ApiPath('system/device/controllers', None, None, None)
    iter_fields = ('uuid', 'validity')

    @staticmethod
    def is_vsmart(device_type):
        return device_type == 'vsmart'

    @staticmethod
    def is_vbond(device_type):
        return device_type == 'vbond'

    @staticmethod
    def is_manage(device_type):
        return device_type == 'vmanage'

    def filtered_iter(self, filter_fn):
        return (
            (item_id, item_name) for item_type, item_id, item_name
            in self.iter('deviceType', *self.iter_fields) if filter_fn(item_type)
        )


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


class DeviceTemplate(ConfigItem):
    api_path = CliOrFeatureApiPath(
        ApiPath('template/device/object', 'template/device/feature', 'template/device'),
        ApiPath('template/device/object', 'template/device/cli', 'template/device')
    )
    store_path = ('device_templates', 'template')
    store_file = '{item_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'
    post_filtered_tags = ('feature', )
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'templateAttached', 'templateConfigurationEdited'}

    @property
    def is_type_cli(self):
        return self.data.get('configType', 'template') == 'file'


@register('template_device', 'device template', DeviceTemplate)
class DeviceTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/device', None, None, None)
    store_file = 'device_templates.json'
    iter_fields = IdName('templateId', 'templateName')

    @staticmethod
    def is_vsmart(device_type, num_attached):
        return device_type == 'vsmart' and num_attached > 0

    @staticmethod
    def is_not_vsmart(device_type, num_attached):
        return device_type != 'vsmart' and num_attached > 0

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
    store_path = ('feature_templates', )
    store_file = '{item_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'
    skip_cmp_tag_set = {'createdOn', 'createdBy', 'lastUpdatedBy', 'lastUpdatedOn', '@rid', 'owner', 'infoTag',
                        'devicesAttached', 'attachedMastersCount'}


@register('template_feature', 'feature template', FeatureTemplate)
class FeatureTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/feature', None, None, None)
    store_file = 'feature_templates.json'
    iter_fields = IdName('templateId', 'templateName')


#
# Policy vSmart
#

class PolicyVsmart(ConfigItem):
    api_path = ApiPath('template/policy/vsmart/definition', 'template/policy/vsmart')
    store_path = ('policy_templates', 'vSmart')
    store_file = '{item_name}.json'
    name_tag = 'policyName'
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


@register('policy_security', 'security policy', PolicySecurity)
class PolicySecurityIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/security', None, None, None)
    store_file = 'policy_templates_security.json'
    iter_fields = IdName('policyId', 'policyName')


#
# Policy definitions
#

# Policy definition base class
class PolicyDef(ConfigItem):
    store_file = '{item_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'
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


# These items showed up in swagger for 19.3 but are not yet configurable
# class PolicyDefDialPeer(PolicyDef):
#     api_path = ApiPath('template/policy/definition/dialpeer')
#     store_path = ('policy_definitions', 'DialPeer')
#
#
# @register('policy_definition', 'dial-peer policy definition', PolicyDefDialPeer)
# class PolicyDefDialPeerIndex(PolicyDefIndex):
#     api_path = ApiPath('template/policy/definition/dialpeer', None, None, None)
#     store_file = 'policy_definitions_dialpeer.json'
#
#
# class PolicyDefPhoneProfile(PolicyDef):
#     api_path = ApiPath('template/policy/definition/srstphoneprofile')
#     store_path = ('policy_definitions', 'PhoneProfile')
#
#
# @register('policy_definition', 'phone profile policy definition', PolicyDefPhoneProfile)
# class PolicyDefPhoneProfileIndex(PolicyDefIndex):
#     api_path = ApiPath('template/policy/definition/srstphoneprofile', None, None, None)
#     store_file = 'policy_definitions_phoneprofile.json'


#
# Policy lists
#

# Policy list base class
class PolicyList(ConfigItem):
    store_file = '{item_name}.json'
    id_tag = 'listId'
    name_tag = 'name'
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


class PolicyListPrefix(PolicyList):
    api_path = ApiPath('template/policy/list/prefix')
    store_path = ('policy_lists', 'Prefix')


@register('policy_list', 'prefix list', PolicyListPrefix)
class PolicyListPrefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/prefix', None, None, None)
    store_file = 'policy_lists_prefix.json'


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
class PolicyListDataprefix(PolicyList):
    api_path = ApiPath('template/policy/list/dataprefix')
    store_path = ('policy_lists', 'DataPrefix')


@register('policy_list', 'data-prefix list', PolicyListDataprefix)
class PolicyListDataprefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataprefix', None, None, None)
    store_file = 'policy_lists_dataprefix.json'


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


class PolicyListDataipv6prefix(PolicyList):
    api_path = ApiPath('template/policy/list/dataipv6prefix')
    store_path = ('policy_lists', 'DataIPv6Prefix')


@register('policy_list', 'data-ipv6-prefix list', PolicyListDataipv6prefix)
class PolicyListDataipv6prefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataipv6prefix', None, None, None)
    store_file = 'policy_lists_dataipv6prefix.json'


class PolicyListIpv6prefix(PolicyList):
    api_path = ApiPath('template/policy/list/ipv6prefix')
    store_path = ('policy_lists', 'IPv6Prefix')


@register('policy_list', 'ipv6-prefix list', PolicyListIpv6prefix)
class PolicyListIpv6prefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/ipv6prefix', None, None, None)
    store_file = 'policy_lists_ipv6prefix.json'


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


# These items showed up in swagger for 19.3 but are not yet configurable
# class PolicyListTransRules(PolicyList):
#     api_path = ApiPath('template/policy/list/translationrules')
#     store_path = ('policy_lists', 'TranslationRules')
#
#
# @register('policy_list', 'translation rules list', PolicyListTransRules)
# class PolicyListTransRulesIndex(PolicyListIndex):
#     api_path = ApiPath('template/policy/list/translationrules', None, None, None)
#     store_file = 'policy_lists_translationrules.json'
#
#
# class PolicyListTransProfile(PolicyList):
#     api_path = ApiPath('template/policy/list/translationprofile')
#     store_path = ('policy_lists', 'TranslationProfile')
#
#
# @register('policy_list', 'translation profile list', PolicyListTransProfile)
# class PolicyListTransProfileIndex(PolicyListIndex):
#     api_path = ApiPath('template/policy/list/translationprofile', None, None, None)
#     store_file = 'policy_lists_translationprofile.json'
#
#
# class PolicyListSupervisoryDisk(PolicyList):
#     api_path = ApiPath('template/policy/list/supervisorydisc')
#     store_path = ('policy_lists', 'SupervisoryDisk')
#
#
# @register('policy_list', 'supervisory disk list', PolicyListSupervisoryDisk)
# class PolicyListSupervisoryDiskIndex(PolicyListIndex):
#     api_path = ApiPath('template/policy/list/supervisorydisc', None, None, None)
#     store_file = 'policy_lists_supervisorydisc.json'
#
#
# class PolicyListMediaProfile(PolicyList):
#     api_path = ApiPath('template/policy/list/mediaprofile')
#     store_path = ('policy_lists', 'MediaProfile')
#
#
# @register('policy_list', 'media profile list', PolicyListMediaProfile)
# class PolicyListMediaProfileIndex(PolicyListIndex):
#     api_path = ApiPath('template/policy/list/mediaprofile', None, None, None)
#     store_file = 'policy_lists_mediaprofile.json'

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
    store_path = ('certificates', )
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
