"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.catalog
 This module implements vManage API Catalog
"""
from collections import namedtuple
from .models_base import IndexConfigItem, ConfigItem, RealtimeItem
from .rest_api import is_version_newer


CATALOG_TAG_ALL = 'all'

# Catalog of configuration items
_catalog = list()   # [(<tag>, <info>, <index_cls>, <item_cls>, <min_version>), ...]

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'info', 'index_cls', 'item_cls', 'min_version'])

# Catalog of realtime items
_rt_catalog = list()  # [(<tag>, <selector>, <info>, <rt_cls>, <min_version>), ...]

RTCatalogEntry = namedtuple('RTCatalogEntry', ['tag', 'selector', 'info', 'rt_cls', 'min_version'])

#
# Configuration catalog functions
#
# Order in which config items need to be deleted (i.e. reverse order in which they need to be pushed), considering
# their high-level dependencies.
_tag_dependency_list = [
    'template_device',
    'template_feature',
    'policy_vsmart',
    'policy_vedge',
    'policy_security',
    'policy_voice',
    'policy_customapp',
    'policy_definition',
    'policy_profile',
    'policy_list',
]


def ordered_tags(tag, single=False, reverse=False):
    """
    Generator which yields the specified tag plus any 'child' tags (i.e. dependent tags), following the order in which
    items need to be removed based on their dependencies (e.g. template_device before template_feature). The overall
    order is defined by _tag_dependency_list.
    If special tag 'all' is used, all items from _tag_dependency_list are yielded.
    :param tag: tag string or 'all'
    :param single: Optional, when True only a the one (first) tag is yielded. Used mainly for convenience of the caller.
    :param reverse: If true, yield tags in reverse order
    :return: Selected tags in order, as per _tag_dependency_list
    """
    find_tag = (tag == CATALOG_TAG_ALL)
    for item in _tag_dependency_list if not reverse else reversed(_tag_dependency_list):
        if not find_tag:
            if item == tag:
                find_tag = True
            else:
                continue
        yield item

        if single:
            break


def register(tag, info, item_cls, min_version=None):
    """
    Decorator used for registering config item index/handler classes with the catalog.
    The class being decorated needs to be a subclass of IndexConfigItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param info: Item information used for logging purposes
    :param item_cls: The config item handler class, needs to be a subclass of ConfigItem
    :param min_version: (optional) Minimum vManage version that supports this catalog item.
    :return: decorator
    """
    def decorator(index_cls):
        if not isinstance(index_cls, type) or not issubclass(index_cls, IndexConfigItem):
            raise CatalogException(f'Invalid config item index class register attempt: {index_cls.__name__}')
        if not isinstance(item_cls, type) or not issubclass(item_cls, ConfigItem):
            raise CatalogException(
                f'Invalid config item class register attempt {index_cls.__name__}: {item_cls.__name__}'
            )
        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException(f'Invalid tag provided for class {index_cls.__name__}: {tag}')
        if tag not in _tag_dependency_list:
            raise CatalogException(f'Unknown tag provided: {tag}')

        _catalog.append(CatalogEntry(tag, info, index_cls, item_cls, min_version))

        return index_cls

    return decorator


def catalog_size():
    """
    Return number of entries in the catalog
    :return: integer
    """
    return len(_catalog)


def catalog_iter(*tags, version=None):
    """
    Return an iterator of (<tag>, <info>, <index_cls>, <item_cls>) tuples matching the specified tag(s) and supported
    by vManage version.
    :param tags: tags indicating catalog entries to return
    :param version: Target vManage version. Only returns catalog items supported by the target vManage.
                    If not specified or None, version is not verified.
    :return: iterator of (<tag>, <info>, <index_cls>, <item_cls>) tuples from the catalog
    """
    def match_tags(catalog_entry):
        return CATALOG_TAG_ALL in tags or catalog_entry.tag in tags

    def match_version(catalog_entry):
        return catalog_entry.min_version is None or version is None or not is_version_newer(version,
                                                                                            catalog_entry.min_version)

    return (
        (entry.tag, entry.info, entry.index_cls, entry.item_cls)
        for entry in _catalog if match_tags(entry) and match_version(entry)
    )


def catalog_tags():
    """
    Return unique tags used by items registered with the catalog
    :return: Set of unique tags
    """
    return {entry.tag for entry in _catalog}


#
# Realtime catalog functions
#
def rt_register(tag, selector, info, min_version=None):
    """
    Decorator used for registering realtime items with the realtime catalog.
    The class being decorated needs to be a subclass of RealtimeItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param selector: String used to further filter entries that match the tags.
    :param info: Item information used for logging purposes
    :param min_version: (optional) Minimum vManage version that supports this catalog item.
    :return: decorator
    """
    def decorator(realtime_cls):
        if not isinstance(realtime_cls, type) or not issubclass(realtime_cls, RealtimeItem):
            raise CatalogException(f'Invalid realtime item class register attempt: {realtime_cls.__name__}')
        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException(f'Invalid tag provided for class {realtime_cls.__name__}: {tag}')
        if not isinstance(selector, str) or selector.lower() == CATALOG_TAG_ALL:
            raise CatalogException(f'Invalid selector provided for class {realtime_cls.__name__}: {selector}')

        _rt_catalog.append(RTCatalogEntry(tag, selector, info, realtime_cls, min_version))

        return realtime_cls

    return decorator


def rt_catalog_size():
    """
    Return number of entries in the realtime catalog
    :return: integer
    """
    return len(_rt_catalog)


def rt_catalog_iter(*tags, version=None):
    """
    Return an iterator of (<info>, <rt_cls>) tuples matching the specified tag(s), selector and supported
    by vManage version.
    :param tags: Tags to filter catalog entries to return. If 2 or more tags are provided, the last one is considered
                 a selector.
    :param version: Target vManage version. Only returns catalog items supported by the target vManage.
                    If not specified or None, version is not verified.
    :return: iterator of (<info>, <rt_cls>) tuples from the realtime catalog
    """
    if len(tags) > 1:
        group_list = tags[:-1]
        selector = tags[-1]
    else:
        group_list = tags
        selector = None

    def match_groups(catalog_entry):
        return CATALOG_TAG_ALL in group_list or catalog_entry.tag in group_list

    def match_selector(catalog_entry):
        return selector is None or catalog_entry.selector == selector

    def match_version(catalog_entry):
        return catalog_entry.min_version is None or version is None or not is_version_newer(version,
                                                                                            catalog_entry.min_version)

    return (
        (entry.info, entry.rt_cls)
        for entry in _rt_catalog if match_groups(entry) and match_selector(entry) and match_version(entry)
    )


def rt_catalog_tags():
    """
    Return unique tags used by items registered with the realtime catalog
    :return: Set of unique tags
    """
    return {entry.tag for entry in _rt_catalog}


def rt_catalog_commands():
    """
    Return set of commands registered with the realtime catalog. These are the combination of tags and selectors
    :return: Set of commands
    """
    return {f'{entry.tag} {entry.selector}' for entry in _rt_catalog}


class CatalogException(Exception):
    """ Exception for config item catalog errors """
    pass
