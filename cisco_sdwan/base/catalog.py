"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.catalog
 This module implements vManage API Catalog
"""
from collections import namedtuple
from .models_base import IndexConfigItem, ConfigItem
from .rest_api import is_version_newer


_catalog = list()   # [(<tag>, <info>, <index_cls>, <item_cls>, <min_version>), ...]

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'info', 'index_cls', 'item_cls', 'min_version'])

CATALOG_TAG_ALL = 'all'

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


def ordered_tags(tag, single=False):
    """
    Generator which yields the specified tag plus any 'child' tags (i.e. dependent tags), following the order in which
    items need to be removed based on their dependencies (e.g. template_device before template_feature). The overall
    order is defined by _tag_dependency_list.
    If special tag 'all' is used, all items from _tag_dependency_list are yielded.
    :param tag: tag string or 'all'
    :param single: Optional, when True only a the one (first) tag is yielded. Used mainly for convenience of the caller.
    :return: Selected tags in order, as per _tag_dependency_list
    """
    find_tag = (tag == CATALOG_TAG_ALL)
    for item in _tag_dependency_list:
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
            raise CatalogException(
                'Invalid config item index class register attempt: {}'.format(index_cls.__name__)
            )
        if not isinstance(item_cls, type) or not issubclass(item_cls, ConfigItem):
            raise CatalogException(
                'invalid config item class register attempt {}: {}'.format(index_cls.__name__, item_cls.__name__)
            )
        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException(
                'Invalid tag provided for class {}: {}'.format(index_cls.__name__, tag)
            )
        if tag not in _tag_dependency_list:
            raise CatalogException(
                'Unknown tag provided: {}'.format(tag)
            )
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


class CatalogException(Exception):
    """ Exception for config item catalog errors """
    pass
