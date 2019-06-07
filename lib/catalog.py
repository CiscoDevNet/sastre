import os.path
import json
import re
from functools import partial
from itertools import zip_longest
from collections import namedtuple

# TODO: Escape filename on load/save when item_name is used

# Each entry in _catalog is a tuple (<tag>, <title>, <index_cls>, <handler_cls>)
_catalog = list()

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'title', 'index_cls', 'item_cls'])

CATALOG_TAG_ALL = 'all'

# Order in which config items need to be configured considering their dependencies
_tag_dependency_list = [
    'policy_list',
    'policy_definition',
    'policy_apply',
    'template_feature',
    'template_device'
]


def ordered_tags(tag):
    """
    Generator that yield the provided tag and any previous tags (i.e. dependent tags). If tag
    is not in _tag_dependency_list (i.e. tag='all'), it yields all items of the list
    :param tag: tag string identifying
    :return: tag items in order
    """
    for tag_item in _tag_dependency_list:
        yield tag_item

        if tag_item == tag:
            break


def register(tag, title, item_cls):
    """
    Decorator used for registering config item index/handler classes with the catalog.
    The class being decorated needs to be a subclass of IndexConfigItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param title: Item title used for logging purposes
    :param item_cls: The config item handler class, needs to be a subclass of ConfigItem
    :return: decorator
    """
    def decorator(index_cls):
        if not isinstance(index_cls, type) or not issubclass(index_cls, IndexConfigItem):
            raise CatalogException('Attempt to register an invalid config item index class: {}'.format(index_cls.__name__))

        if not isinstance(item_cls, type) or not issubclass(item_cls, ConfigItem):
            raise CatalogException('Attempt to register an invalid config item class with {}: {}'.format(index_cls.__name__, item_cls.__name__))

        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException('Invalid tag provided for class {}: {}'.format(index_cls.__name__, tag))

        _catalog.append(CatalogEntry(tag, title, index_cls, item_cls))

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
    Return an iterator of CatalogEntry matching the specified tag
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


class ApiPath:
    """ Groups the API path for different operations available in an API item (i.e. get, post, put, delete).
        Each field contains a str with the API path, or None if the particular operations is not supported on this item.
    """
    __slots__ = ('get', 'post', 'put', 'delete')

    def __init__(self, get, *other_ops):
        """
        :param get: URL path for get operations
        :param other_ops: URL path for post, put and delete operations, in this order. If an item is not specified
                          the same URL as the last operation provided is used.
        """
        self.get = get
        last_op = other_ops[-1] if other_ops else get
        for field, value in zip_longest(self.__slots__[1:], other_ops, fillvalue=last_op):
            setattr(self, field, value)


class ConfigItem:
    api_path = None
    store_path = None
    store_file = None

    id_tag = None
    name_tag = None
    factory_default_tag = 'factoryDefault'
    readonly_tag = 'readOnly'

    root_dir = 'data'

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item
        """
        self.data = data

    @classmethod
    def load(cls, node_dir, **kwargs):
        """
        Factory method that loads data from a json file and returns a ConfigItem instance with that data

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :param kwargs: kwargs passed to str.format for variable substitution on the filename.
        :return: ConfigItem object, or None if file does not exist.
        """
        file = os.path.join(os.path.join(cls.root_dir, node_dir, *cls.store_path),
                            cls.store_file.format(**kwargs) if len(kwargs) > 0 else cls.store_file)

        if not os.path.exists(file):
            return None

        with open(file, 'r') as read_f:
            data = json.load(read_f)

        return cls(data)

    def save(self, node_dir, **kwargs):
        """
        Save data (i.e. self.data) to a json file

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :param kwargs: kwargs passed to str.format for variable substitution on the filename.
        :return: True indicates data has been saved. False indicates no data to save (and no file has been created).
        """
        if self.data is None or len(self.data) == 0:
            return False

        dir_path = os.path.join(self.root_dir, node_dir, *self.store_path)
        os.makedirs(dir_path, exist_ok=True)

        filename = self.store_file.format(**kwargs) if len(kwargs) > 0 else self.store_file

        with open(os.path.join(dir_path, filename), 'w') as write_f:
            json.dump(self.data, write_f, indent=2)

        return True

    @property
    def uuid(self):
        return self.data[self.id_tag] if self.id_tag is not None else None

    @property
    def name(self):
        return self.data[self.name_tag] if self.name_tag is not None else None

    @property
    def is_readonly(self):
        return self.data.get(self.factory_default_tag, False) or self.data.get(self.readonly_tag, False)

    def post_data(self, id_mapping_dict, new_name=None):
        """
        Build payload to be used for POST requests against this config item. From self.data, perform replacements
        defined in replacemnts_dict, remove item id and rename item with new_name (if provided).
        :param id_mapping_dict: {<old item id>: <new item id>} dict. Matches of <old item id> are replaced with
        <new item id>
        :param new_name: String containing new name
        :return: dict containing payload for POST requests
        """
        def replace_id(match):
            matched_id = match.group(0)
            return id_mapping_dict.get(matched_id, matched_id)

        # Remove item id
        filtered_keys = {
            self.id_tag,
        }
        post_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        # Rename item
        if new_name is not None:
            post_dict[self.name_tag] = new_name

        # Perform id replacements
        post_dict_json = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                                replace_id, json.dumps(post_dict))

        return json.loads(post_dict_json)

    def __str__(self):
        return json.dumps(self.data, indent=2)

    def __repr__(self):
        return json.dumps(self.data)


class IndexConfigItem(ConfigItem):
    iter_fields = None

    store_path = ('index', )

    def __iter__(self):
        return map(partial(fields, self.iter_fields), self.data)


def fields(field_keys, item):
    if isinstance(field_keys, str):
        return item[field_keys]

    return tuple(item[field] for field in field_keys)


class CatalogException(Exception):
    """ Exception config item catalog errors """
    pass
