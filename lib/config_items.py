from lib.catalog import ConfigItem, IndexConfigItem, ApiPath, register


#
# Templates
#
class DeviceTemplate(ConfigItem):
    api_path = ApiPath('template/device/object', 'template/device/feature', 'template/device')
    store_path = ('templates', 'device_template')
    store_file = '{template_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'


@register('template_device', 'device template', DeviceTemplate)
class DeviceTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/device', None, None, None)
    store_file = 'device_template_list.json'
    iter_fields = ('templateId', 'templateName')


# This is a special case handled under DeviceTemplate
class DeviceTemplateAttached(IndexConfigItem):
    api_path = ApiPath('template/device/config/attached', 'template/device/config/attachfeature', None, None)
    store_path = ('templates', 'device_template_attached')
    store_file = '{template_name}.json'
    iter_fields = 'uuid'


# This is a special case handled under DeviceTemplate
class DeviceTemplateValues(ConfigItem):
    api_path = ApiPath(None, 'template/device/config/input', None, None)
    store_path = ('templates', 'device_template_values')
    store_file = '{template_name}.json'

    @staticmethod
    def api_params(template_id, device_id_list):
        return {
            "deviceIds": device_id_list,
            "isEdited": False,
            "isMasterEdited": False,
            "templateId": template_id
        }


class FeatureTemplate(ConfigItem):
    api_path = ApiPath('template/feature/object', 'template/feature')
    store_path = ('templates', 'feature_template')
    store_file = '{template_name}.json'
    id_tag = 'templateId'
    name_tag = 'templateName'


@register('template_feature', 'feature template', FeatureTemplate)
class FeatureTemplateIndex(IndexConfigItem):
    api_path = ApiPath('template/feature', None, None, None)
    store_file = 'feature_template_list.json'
    iter_fields = ('templateId', 'templateName')


#
# Policy apply
#

class PolicyVsmart(ConfigItem):
    api_path = ApiPath('template/policy/vsmart/definition', 'template/policy/vsmart')
    store_path = ('templates', 'vsmart_policy')
    store_file = '{template_name}.json'
    name_tag = 'policyName'


@register('policy_apply', 'VSMART policy', PolicyVsmart)
class PolicyVsmartIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vsmart', None, None, None)
    store_file = 'vsmart_policy_list.json'
    iter_fields = ('policyId', 'policyName')


class PolicyVedge(ConfigItem):
    api_path = ApiPath('template/policy/vedge/definition', 'template/policy/vedge')
    store_path = ('templates', 'vedge_policy')
    store_file = '{template_name}.json'
    name_tag = 'policyName'


@register('policy_apply', 'VEDGE policy', PolicyVedge)
class PolicyVedgeIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vedge', None, None, None)
    store_file = 'vedge_policy_list.json'
    iter_fields = ('policyId', 'policyName')


#
# Policy definitions
#

class PolicyDefData(ConfigItem):
    api_path = ApiPath('template/policy/definition/data')
    store_path = ('templates', 'policy_definition_data')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'DATA policy definition', PolicyDefData)
class PolicyDefDataIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/data', None, None, None)
    store_file = 'data_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefMesh(ConfigItem):
    api_path = ApiPath('template/policy/definition/mesh')
    store_path = ('templates', 'policy_definition_mesh')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'MESH policy definition', PolicyDefMesh)
class PolicyDefMeshIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/mesh', None, None, None)
    store_file = 'mesh_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefRewriteRule(ConfigItem):
    api_path = ApiPath('template/policy/definition/rewriterule')
    store_path = ('templates', 'policy_definition_rewriterule')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'REWRITE RULE policy definition', PolicyDefRewriteRule)
class PolicyDefRewriteRuleIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/rewriterule', None, None, None)
    store_file = 'rewrite_rule_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefAclv6(ConfigItem):
    api_path = ApiPath('template/policy/definition/aclv6')
    store_path = ('templates', 'policy_definition_aclv6')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'ACLv6 policy definition', PolicyDefAclv6)
class PolicyDefAclv6Index(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/aclv6', None, None, None)
    store_file = 'aclv6_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefQosmap(ConfigItem):
    api_path = ApiPath('template/policy/definition/qosmap')
    store_path = ('templates', 'policy_definition_qosmap')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'QOS Map policy definition', PolicyDefQosmap)
class PolicyDefQosmapIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/qosmap', None, None, None)
    store_file = 'qosmap_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefUrlfiltering(ConfigItem):
    api_path = ApiPath('template/policy/definition/urlfiltering')
    store_path = ('templates', 'policy_definition_urlfiltering')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'URL filtering policy definition', PolicyDefUrlfiltering)
class PolicyDefUrlfilteringIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/urlfiltering', None, None, None)
    store_file = 'urlfiltering_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefZonebasedfw(ConfigItem):
    api_path = ApiPath('template/policy/definition/zonebasedfw')
    store_path = ('templates', 'policy_definition_zonebasedfw')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'Zone-based firewall policy definition', PolicyDefZonebasedfw)
class PolicyDefZonebasedfwIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/zonebasedfw', None, None, None)
    store_file = 'zonebasedfw_policy_list.json'
    iter_fields = ('definitionId', 'name')


class PolicyDefApproute(ConfigItem):
    api_path = ApiPath('template/policy/definition/approute')
    store_path = ('templates', 'policy_definition_approute')
    store_file = '{template_name}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


@register('policy_definition', 'AppRoute policy definition', PolicyDefApproute)
class PolicyDefApprouteIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/definition/approute', None, None, None)
    store_file = 'approute_policy_list.json'
    iter_fields = ('definitionId', 'name')


#
# Policy lists
#

class PolicyListVpn(ConfigItem):
    api_path = ApiPath('template/policy/list/vpn')
    store_path = ('templates', 'policy_list_vpn')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'VPN-list', PolicyListVpn)
class PolicyListVpnIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/vpn', None, None, None)
    store_file = 'vpn_list_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListUrlWhiteList(ConfigItem):
    api_path = ApiPath('template/policy/list/urlwhitelist')
    store_path = ('templates', 'policy_list_urlwhitelist')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'URL-Whitelist', PolicyListUrlWhiteList)
class PolicyListUrlWhileListIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/urlwhitelist', None, None, None)
    store_file = 'urlwhitelist_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListUrlBlackList(ConfigItem):
    api_path = ApiPath('template/policy/list/urlblacklist')
    store_path = ('templates', 'policy_list_urlblacklist')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'URL-Blacklist', PolicyListUrlBlackList)
class PolicyListUrlBlackListIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/urlblacklist', None, None, None)
    store_file = 'urlblacklist_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListPolicer(ConfigItem):
    api_path = ApiPath('template/policy/list/policer')
    store_path = ('templates', 'policy_list_policer')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Policer-list', PolicyListPolicer)
class PolicyListPolicerIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/policer', None, None, None)
    store_file = 'policer_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListDataPrefixAll(ConfigItem):
    api_path = ApiPath('template/policy/list/dataprefixall')
    store_path = ('templates', 'policy_list_dataprefixall')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Data-prefix-all-list', PolicyListDataPrefixAll)
class PolicyListDataPrefixAllIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/dataprefixall', None, None, None)
    store_file = 'dataprefixall_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListIpsSignature(ConfigItem):
    api_path = ApiPath('template/policy/list/ipssignature')
    store_path = ('templates', 'policy_list_ipssignature')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'IPS-Signature-list', PolicyListIpsSignature)
class PolicyListIpsSignatureIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/ipssignature', None, None, None)
    store_file = 'ipssignature_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListClass(ConfigItem):
    api_path = ApiPath('template/policy/list/class')
    store_path = ('templates', 'policy_list_class')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Class-list', PolicyListClass)
class PolicyListClassIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/class', None, None, None)
    store_file = 'class_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListUmbrellaData(ConfigItem):
    api_path = ApiPath('template/policy/list/umbrelladata')
    store_path = ('templates', 'policy_list_umbrelladata')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Umbrella-data-list', PolicyListUmbrellaData)
class PolicyListUmbrellaDataIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/umbrelladata', None, None, None)
    store_file = 'umbrelladata_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListPrefix(ConfigItem):
    api_path = ApiPath('template/policy/list/prefix')
    store_path = ('templates', 'policy_list_prefix')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Prefix-list', PolicyListPrefix)
class PolicyListPrefixIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/prefix', None, None, None)
    store_file = 'prefix_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListPrefixAll(ConfigItem):
    api_path = ApiPath('template/policy/list/ipprefixall')
    store_path = ('templates', 'policy_list_ipprefixall')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'IP prefix-list all', PolicyListPrefixAll)
class PolicyListPrefixAllIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/ipprefixall', None, None, None)
    store_file = 'ipprefixall_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListSite(ConfigItem):
    api_path = ApiPath('template/policy/list/site')
    store_path = ('templates', 'policy_list_site')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Site-list', PolicyListSite)
class PolicyListSiteIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/site', None, None, None)
    store_file = 'site_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListExtcommunity(ConfigItem):
    api_path = ApiPath('template/policy/list/extcommunity')
    store_path = ('templates', 'policy_list_extcommunity')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Extended community list', PolicyListExtcommunity)
class PolicyListExtcommunityIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/extcommunity', None, None, None)
    store_file = 'extcommunity_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListDataprefix(ConfigItem):
    api_path = ApiPath('template/policy/list/dataprefix')
    store_path = ('templates', 'policy_list_dataprefix')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Data prefix list', PolicyListDataprefix)
class PolicyListDataprefixIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/dataprefix', None, None, None)
    store_file = 'dataprefix_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListMirror(ConfigItem):
    api_path = ApiPath('template/policy/list/mirror')
    store_path = ('templates', 'policy_list_mirror')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Mirror list', PolicyListMirror)
class PolicyListMirrorIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/mirror', None, None, None)
    store_file = 'mirror_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListApplication(ConfigItem):
    api_path = ApiPath('template/policy/list/app')
    store_path = ('templates', 'policy_list_app')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Application list', PolicyListApplication)
class PolicyListApplicationIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/app', None, None, None)
    store_file = 'app_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListLocalApplication(ConfigItem):
    api_path = ApiPath('template/policy/list/localapp')
    store_path = ('templates', 'policy_list_localapp')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'Local application list', PolicyListLocalApplication)
class PolicyListLocalApplicationIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/localapp', None, None, None)
    store_file = 'localapp_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListSla(ConfigItem):
    api_path = ApiPath('template/policy/list/sla')
    store_path = ('templates', 'policy_list_sla')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'SLA class list', PolicyListSla)
class PolicyListSlaIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/sla', None, None, None)
    store_file = 'sla_policy_list.json'
    iter_fields = ('listId', 'name')


class PolicyListColor(ConfigItem):
    api_path = ApiPath('template/policy/list/color')
    store_path = ('templates', 'policy_list_color')
    store_file = '{template_name}.json'
    id_tag = 'listId'
    name_tag = 'name'


@register('policy_list', 'SLA class list', PolicyListColor)
class PolicyListColorIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/list/color', None, None, None)
    store_file = 'color_policy_list.json'
    iter_fields = ('listId', 'name')


# TODO: Policy Zone list Builder - zone  next

