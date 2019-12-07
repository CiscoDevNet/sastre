"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.catalog
 This module implements vManage API Catalog
"""
from collections import namedtuple
from .models_base import IndexConfigItem, ConfigItem

_catalog = list()   # [(<tag>, <info>, <index_cls>, <item_cls>), ...]

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'info', 'index_cls', 'item_cls'])

CATALOG_TAG_ALL = 'all'

# Order in which config items need to be deleted (i.e. reverse order in which they need to be pushed), considering
# their high-level dependencies.
_tag_dependency_list = [
    'template_device',
    'template_feature',
    'policy_vsmart',
    'policy_vedge',
    'policy_security',
    'policy_definition',
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


def register(tag, info, item_cls):
    """
    Decorator used for registering config item index/handler classes with the catalog.
    The class being decorated needs to be a subclass of IndexConfigItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param info: Item information used for logging purposes
    :param item_cls: The config item handler class, needs to be a subclass of ConfigItem
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
        _catalog.append(CatalogEntry(tag, info, index_cls, item_cls))

        return index_cls

    return decorator


def catalog_size():
    """
    Return number of entries in the catalog
    :return: integer
    """
    return len(_catalog)


def catalog_entries(*tags):
    """
    Return an iterator of CatalogEntry matching the specified tag(s)
    :param tags: tags indicating catalog entries to return
    :return: iterator of CatalogEntry
    """
    def match_tags(catalog_entry):
        return True if (CATALOG_TAG_ALL in tags) or (catalog_entry.tag in tags) else False

    return filter(match_tags, _catalog)


def catalog_tags():
    """
    Return unique tags used by items registered with the catalog
    :return: Set of unique tags
    """
    return set(map(lambda x: x.tag, _catalog))


class CatalogException(Exception):
    """ Exception for config item catalog errors """
    pass
