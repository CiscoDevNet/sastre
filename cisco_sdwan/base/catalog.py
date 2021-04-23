"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.catalog
 This module implements vManage API Catalogs
"""
from typing import NamedTuple, Union, Optional, Iterator
from enum import Enum
from .models_base import IndexConfigItem, ConfigItem, RealtimeItem, BulkStateItem, BulkStatsItem
from .rest_api import is_version_newer


CATALOG_TAG_ALL = 'all'


# Catalog for configuration data items
class CatalogItem(NamedTuple):
    tag: str
    info: str
    index_cls: type
    item_cls: type
    min_version: Union[str, None]


_catalog = list()   # [(<tag>, <info>, <index_cls>, <item_cls>, <min_version>), ...]


# Catalog for operational data items
class OpType(Enum):
    STATS = BulkStatsItem
    STATE = BulkStateItem
    RT = RealtimeItem

    @classmethod
    def from_subclass(cls, op_cls):
        return cls(op_cls.__bases__[0])


class OpCatalogItem(NamedTuple):
    tag: str
    selector: str
    info: str
    op_cls: type
    min_version: Union[str, None]


_op_catalog = dict()  # {<OpType>: [(<tag>, <selector>, <info>, <op_cls>, <min_version>), ...]}


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


def ordered_tags(tag: str, single: bool = False, reverse: bool = False) -> Iterator[str]:
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


def register(tag: str, info: str, item_cls: type, min_version: Optional[str] = None):
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

        _catalog.append(CatalogItem(tag, info, index_cls, item_cls, min_version))

        return index_cls

    return decorator


def catalog_size() -> int:
    """
    Return number of entries in the catalog
    :return: integer
    """
    return len(_catalog)


def catalog_iter(*tags: str, version: Optional[str] = None) -> Iterator[tuple]:
    """
    Return an iterator of (<tag>, <info>, <index_cls>, <item_cls>) tuples matching the specified tag(s) and supported
    by vManage version.
    :param tags: tags indicating catalog entries to return
    :param version: Target vManage version. Only returns catalog items supported by the target vManage.
                    If not specified or None, version is not verified.
    :return: iterator of (<tag>, <info>, <index_cls>, <item_cls>) tuples from the catalog
    """
    def match_tags(clog_item):
        return CATALOG_TAG_ALL in tags or clog_item.tag in tags

    def match_version(clog_item):
        return clog_item.min_version is None or version is None or not is_version_newer(version, clog_item.min_version)

    return (
        (item.tag, item.info, item.index_cls, item.item_cls)
        for item in _catalog if match_tags(item) and match_version(item)
    )


def catalog_tags() -> set:
    """
    Return unique tags used by items registered with the catalog
    :return: Set of unique tags
    """
    return {entry.tag for entry in _catalog}


#
# Operational data catalog functions
#
def op_register(tag: str, selector: str, info: str, min_version: Optional[str] = None):
    """
    Decorator used for registering operational-data items with the op catalog.
    The class being decorated needs to be a subclass of OperationalItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param selector: String used to further filter entries that match the tags.
    :param info: Item information used for logging purposes
    :param min_version: (optional) Minimum vManage version that supports this catalog item.
    :return: decorator
    """
    def decorator(op_cls):
        try:
            op_type = OpType.from_subclass(op_cls)
        except ValueError:
            raise CatalogException(f'Invalid operational-data class register attempt: {op_cls.__name__}') from None

        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException(f'Invalid tag provided for class {op_cls.__name__}: {tag}')
        if not isinstance(selector, str) or selector.lower() == CATALOG_TAG_ALL:
            raise CatalogException(f'Invalid selector provided for class {op_cls.__name__}: {selector}')

        _op_catalog.setdefault(op_type, []).append(OpCatalogItem(tag, selector, info, op_cls, min_version))

        return op_cls

    return decorator


def op_catalog_size() -> int:
    """
    Return number of entries in the operational-data catalog
    :return: integer
    """
    return sum(len(entries) for entries in _op_catalog.values())


def op_catalog_iter(op_type: OpType, *tags: str, version: Optional[str] = None) -> Iterator[tuple]:
    """
    Return an iterator of (<info>, <op_cls>) tuples matching the specified tag(s), selector and supported
    by vManage version.
    :param op_type: OpType enum indicating type of operational-data
    :param tags: Tags to filter catalog entries to return. If 2 or more tags are provided, the last one is considered
                 a selector.
    :param version: Target vManage version. Only returns catalog items supported by the target vManage.
                    If not specified or None, version is not verified.
    :return: iterator of (<info>, <op_cls>) tuples from the operational-data catalog
    """
    if len(tags) > 1:
        group_list = tags[:-1]
        selector = tags[-1]
    else:
        group_list = tags
        selector = None

    def match_group(clog_item):
        return CATALOG_TAG_ALL in group_list or clog_item.tag in group_list

    def match_selector(clog_item):
        return selector is None or clog_item.selector == selector

    def match_version(clog_item):
        return clog_item.min_version is None or version is None or not is_version_newer(version, clog_item.min_version)

    return (
        (item.info, item.op_cls)
        for item in _op_catalog.get(op_type, []) if match_group(item) and match_selector(item) and match_version(item)
    )


def op_catalog_tags(op_type: OpType) -> set:
    """
    Return unique tags used by items registered with the operational-data catalog group
    :param op_type: OpType enum indicating type of operational-data
    :return: Set of unique tags
    """
    return {entry.tag for entry in _op_catalog.get(op_type, [])}


def op_catalog_commands(op_type: OpType) -> set:
    """
    Return set of commands registered with the operational-data catalog group. These are the combination of tags and
    selectors
    :param op_type: OpType enum indicating type of operational-data
    :return: Set of commands
    """
    return {f'{entry.tag} {entry.selector}' for entry in _op_catalog.get(op_type, [])}


class CatalogException(Exception):
    """ Exception for config item catalog errors """
    pass
