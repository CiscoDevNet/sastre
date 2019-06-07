from lib.catalog import ConfigItem, IndexConfigItem, ApiPath, register


#
# Templates
#
class DeviceTemplate(ConfigItem):
    api_path = ApiPath('template/device/object', 'template/device/feature', 'template/device')
    store_path = ('templates', 'device_template')
    store_file = '{item_id}.json'
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
    store_file = '{item_id}.json'
    iter_fields = 'uuid'


# This is a special case handled under DeviceTemplate
class DeviceTemplateValues(ConfigItem):
    api_path = ApiPath(None, 'template/device/config/input', None, None)
    store_path = ('templates', 'device_template_values')
    store_file = '{item_id}.json'

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
    store_file = '{item_id}.json'
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
    store_file = '{item_id}.json'
    name_tag = 'policyName'


@register('policy_apply', 'VSMART policy', PolicyVsmart)
class PolicyVsmartIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vsmart', None, None, None)
    store_file = 'vsmart_policy_list.json'
    iter_fields = ('policyId', 'policyName')


class PolicyVedge(ConfigItem):
    api_path = ApiPath('template/policy/vedge/definition', 'template/policy/vedge')
    store_path = ('templates', 'vedge_policy')
    store_file = '{item_id}.json'
    name_tag = 'policyName'


@register('policy_apply', 'VEDGE policy', PolicyVedge)
class PolicyVedgeIndex(IndexConfigItem):
    api_path = ApiPath('template/policy/vedge', None, None, None)
    store_file = 'vedge_policy_list.json'
    iter_fields = ('policyId', 'policyName')


#
# Policy definitions
#

# Policy definition base class
class PolicyDef(ConfigItem):
    store_file = '{item_id}.json'
    id_tag = 'definitionId'
    name_tag = 'name'


# Policy definition index base class
class PolicyDefIndex(IndexConfigItem):
    iter_fields = ('definitionId', 'name')


class PolicyDefData(PolicyDef):
    api_path = ApiPath('template/policy/definition/data')
    store_path = ('templates', 'policy_definition_data')


@register('policy_definition', 'data policy definition', PolicyDefData)
class PolicyDefDataIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/data', None, None, None)
    store_file = 'data_policy_list.json'


class PolicyDefMesh(PolicyDef):
    api_path = ApiPath('template/policy/definition/mesh')
    store_path = ('templates', 'policy_definition_mesh')


@register('policy_definition', 'mesh policy definition', PolicyDefMesh)
class PolicyDefMeshIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/mesh', None, None, None)
    store_file = 'mesh_policy_list.json'


class PolicyDefRewriteRule(PolicyDef):
    api_path = ApiPath('template/policy/definition/rewriterule')
    store_path = ('templates', 'policy_definition_rewriterule')


@register('policy_definition', 'rewrite-rule policy definition', PolicyDefRewriteRule)
class PolicyDefRewriteRuleIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/rewriterule', None, None, None)
    store_file = 'rewrite_rule_policy_list.json'


class PolicyDefAclv6(PolicyDef):
    api_path = ApiPath('template/policy/definition/aclv6')
    store_path = ('templates', 'policy_definition_aclv6')


@register('policy_definition', 'ACLv6 policy definition', PolicyDefAclv6)
class PolicyDefAclv6Index(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/aclv6', None, None, None)
    store_file = 'aclv6_policy_list.json'


class PolicyDefQosmap(PolicyDef):
    api_path = ApiPath('template/policy/definition/qosmap')
    store_path = ('templates', 'policy_definition_qosmap')


@register('policy_definition', 'QOS-map policy definition', PolicyDefQosmap)
class PolicyDefQosmapIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/qosmap', None, None, None)
    store_file = 'qosmap_policy_list.json'


class PolicyDefUrlfiltering(PolicyDef):
    api_path = ApiPath('template/policy/definition/urlfiltering')
    store_path = ('templates', 'policy_definition_urlfiltering')


@register('policy_definition', 'URL-filtering policy definition', PolicyDefUrlfiltering)
class PolicyDefUrlfilteringIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/urlfiltering', None, None, None)
    store_file = 'urlfiltering_policy_list.json'


class PolicyDefZonebasedfw(PolicyDef):
    api_path = ApiPath('template/policy/definition/zonebasedfw')
    store_path = ('templates', 'policy_definition_zonebasedfw')


@register('policy_definition', 'zone-based firewall policy definition', PolicyDefZonebasedfw)
class PolicyDefZonebasedfwIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/zonebasedfw', None, None, None)
    store_file = 'zonebasedfw_policy_list.json'


class PolicyDefApproute(PolicyDef):
    api_path = ApiPath('template/policy/definition/approute')
    store_path = ('templates', 'policy_definition_approute')


@register('policy_definition', 'appRoute policy definition', PolicyDefApproute)
class PolicyDefApprouteIndex(PolicyDefIndex):
    api_path = ApiPath('template/policy/definition/approute', None, None, None)
    store_file = 'approute_policy_list.json'


#
# Policy lists
#

# Policy list base class
class PolicyList(ConfigItem):
    store_file = '{item_id}.json'
    id_tag = 'listId'
    name_tag = 'name'


# Policy list index base class
class PolicyListIndex(IndexConfigItem):
    iter_fields = ('listId', 'name')


class PolicyListVpn(PolicyList):
    api_path = ApiPath('template/policy/list/vpn')
    store_path = ('templates', 'policy_list_vpn')


@register('policy_list', 'VPN list', PolicyListVpn)
class PolicyListVpnIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/vpn', None, None, None)
    store_file = 'vpn_list_policy_list.json'


class PolicyListUrlWhiteList(PolicyList):
    api_path = ApiPath('template/policy/list/urlwhitelist')
    store_path = ('templates', 'policy_list_urlwhitelist')


@register('policy_list', 'URL-whitelist list', PolicyListUrlWhiteList)
class PolicyListUrlWhileListIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/urlwhitelist', None, None, None)
    store_file = 'urlwhitelist_policy_list.json'


class PolicyListUrlBlackList(PolicyList):
    api_path = ApiPath('template/policy/list/urlblacklist')
    store_path = ('templates', 'policy_list_urlblacklist')


@register('policy_list', 'URL-blacklist list', PolicyListUrlBlackList)
class PolicyListUrlBlackListIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/urlblacklist', None, None, None)
    store_file = 'urlblacklist_policy_list.json'


class PolicyListPolicer(PolicyList):
    api_path = ApiPath('template/policy/list/policer')
    store_path = ('templates', 'policy_list_policer')


@register('policy_list', 'policer list', PolicyListPolicer)
class PolicyListPolicerIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/policer', None, None, None)
    store_file = 'policer_policy_list.json'


class PolicyListDataPrefixAll(PolicyList):
    api_path = ApiPath('template/policy/list/dataprefixall')
    store_path = ('templates', 'policy_list_dataprefixall')


@register('policy_list', 'data-prefix-all list', PolicyListDataPrefixAll)
class PolicyListDataPrefixAllIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataprefixall', None, None, None)
    store_file = 'dataprefixall_policy_list.json'


class PolicyListIpsSignature(PolicyList):
    api_path = ApiPath('template/policy/list/ipssignature')
    store_path = ('templates', 'policy_list_ipssignature')


@register('policy_list', 'IPS-signature list', PolicyListIpsSignature)
class PolicyListIpsSignatureIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/ipssignature', None, None, None)
    store_file = 'ipssignature_policy_list.json'


class PolicyListClass(PolicyList):
    api_path = ApiPath('template/policy/list/class')
    store_path = ('templates', 'policy_list_class')


@register('policy_list', 'class list', PolicyListClass)
class PolicyListClassIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/class', None, None, None)
    store_file = 'class_policy_list.json'


class PolicyListUmbrellaData(PolicyList):
    api_path = ApiPath('template/policy/list/umbrelladata')
    store_path = ('templates', 'policy_list_umbrelladata')


@register('policy_list', 'umbrella-data list', PolicyListUmbrellaData)
class PolicyListUmbrellaDataIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/umbrelladata', None, None, None)
    store_file = 'umbrelladata_policy_list.json'


class PolicyListPrefix(PolicyList):
    api_path = ApiPath('template/policy/list/prefix')
    store_path = ('templates', 'policy_list_prefix')


@register('policy_list', 'prefix list', PolicyListPrefix)
class PolicyListPrefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/prefix', None, None, None)
    store_file = 'prefix_policy_list.json'


class PolicyListSite(PolicyList):
    api_path = ApiPath('template/policy/list/site')
    store_path = ('templates', 'policy_list_site')


@register('policy_list', 'site list', PolicyListSite)
class PolicyListSiteIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/site', None, None, None)
    store_file = 'site_policy_list.json'


class PolicyListExtcommunity(PolicyList):
    api_path = ApiPath('template/policy/list/extcommunity')
    store_path = ('templates', 'policy_list_extcommunity')


@register('policy_list', 'extended-community list', PolicyListExtcommunity)
class PolicyListExtcommunityIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/extcommunity', None, None, None)
    store_file = 'extcommunity_policy_list.json'


class PolicyListDataprefix(PolicyList):
    api_path = ApiPath('template/policy/list/dataprefix')
    store_path = ('templates', 'policy_list_dataprefix')


@register('policy_list', 'data-prefix list', PolicyListDataprefix)
class PolicyListDataprefixIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/dataprefix', None, None, None)
    store_file = 'dataprefix_policy_list.json'


class PolicyListMirror(PolicyList):
    api_path = ApiPath('template/policy/list/mirror')
    store_path = ('templates', 'policy_list_mirror')


@register('policy_list', 'mirror list', PolicyListMirror)
class PolicyListMirrorIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/mirror', None, None, None)
    store_file = 'mirror_policy_list.json'


class PolicyListApplication(PolicyList):
    api_path = ApiPath('template/policy/list/app')
    store_path = ('templates', 'policy_list_app')


@register('policy_list', 'application list', PolicyListApplication)
class PolicyListApplicationIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/app', None, None, None)
    store_file = 'app_policy_list.json'


class PolicyListLocalApplication(PolicyList):
    api_path = ApiPath('template/policy/list/localapp')
    store_path = ('templates', 'policy_list_localapp')


@register('policy_list', 'local-application list', PolicyListLocalApplication)
class PolicyListLocalApplicationIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/localapp', None, None, None)
    store_file = 'localapp_policy_list.json'


class PolicyListSla(PolicyList):
    api_path = ApiPath('template/policy/list/sla')
    store_path = ('templates', 'policy_list_sla')


@register('policy_list', 'SLA-class list', PolicyListSla)
class PolicyListSlaIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/sla', None, None, None)
    store_file = 'sla_policy_list.json'


class PolicyListColor(PolicyList):
    api_path = ApiPath('template/policy/list/color')
    store_path = ('templates', 'policy_list_color')


@register('policy_list', 'color list', PolicyListColor)
class PolicyListColorIndex(PolicyListIndex):
    api_path = ApiPath('template/policy/list/color', None, None, None)
    store_file = 'color_policy_list.json'


# TODO: Policy Zone list Builder - zone  next

