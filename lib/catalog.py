import os.path
import json
import re
from functools import partial
from itertools import zip_longest
from collections import namedtuple


_catalog = list()   # [(<tag>, <title>, <index_cls>, <item_cls>), ...]

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'title', 'index_cls', 'item_cls'])

CATALOG_TAG_ALL = 'all'

# Reverse order in which config items need to be pushed, considering their high-level dependencies
_tag_dependency_list = [
    'template_device',
    'template_feature',
    'policy_vsmart',
    'policy_vedge',
    'policy_definition',
    'policy_list',
]


def sequenced_tags(tag):
    """
    Generator which yields the specified tag plus any 'child' tags (i.e. dependent tags), as defined by
    _tag_dependency_list. If special tag 'all' is used, all items from _tag_dependency_list are yielded.
    :param tag: tag string or 'all'
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
    """
    Groups the API path for different operations available in an API item (i.e. get, post, put, delete).
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


class ConditionalApiPath:
    def __init__(self, api_path_feature, api_path_cli):
        self.api_path_feature = api_path_feature
        self.api_path_cli = api_path_cli

    def __get__(self, instance, owner):
        # If called from class, assume its a feature template
        is_cli_template = instance is not None and instance.data.get('configType', 'template') == 'file'

        return self.api_path_cli if is_cli_template else self.api_path_feature


class ApiItem:
    """
    ApiItem represents a vManage API element defined by an ApiPath with GET, POST, PUT and DELETE paths. An instance
    of this class can be created to store the contents of that vManage API element (self.data field).
    """
    api_path = None     # An ApiPath instance
    id_tag = None
    name_tag = None

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this api item
        """
        self.data = data

    @property
    def uuid(self):
        return self.data[self.id_tag] if self.id_tag is not None else None

    @property
    def name(self):
        return self.data[self.name_tag] if self.name_tag is not None else None

    @property
    def is_empty(self):
        return self.data is None or len(self.data) == 0

    def __str__(self):
        return json.dumps(self.data, indent=2)

    def __repr__(self):
        return json.dumps(self.data)


class ConfigItem(ApiItem):
    """
    ConfigItem is an ApiItem that can be backed up and restored
    """
    store_path = None
    store_file = None
    root_dir = 'data'
    factory_default_tag = 'factoryDefault'
    readonly_tag = 'readOnly'
    post_filtered_tags = None

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item
        """
        super().__init__(data)

    @property
    def is_readonly(self):
        return self.data.get(self.factory_default_tag, False) or self.data.get(self.readonly_tag, False)

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
        if self.is_empty:
            return False

        dir_path = os.path.join(self.root_dir, node_dir, *self.store_path)
        os.makedirs(dir_path, exist_ok=True)

        filename = self.store_file.format(**kwargs) if len(kwargs) > 0 else self.store_file

        with open(os.path.join(dir_path, filename), 'w') as write_f:
            json.dump(self.data, write_f, indent=2)

        return True

    def post_data(self, id_mapping_dict, new_name=None):
        """
        Build payload to be used for POST requests against this config item. From self.data, perform item id
        replacements defined in id_mapping_dict, also remove item id and rename item with new_name (if provided).
        :param id_mapping_dict: {<old item id>: <new item id>} dict. Matches of <old item id> are replaced with
        <new item id>
        :param new_name: String containing new name
        :return: Dict containing payload for POST requests
        """
        # Delete keys that shouldn't be on post requests
        filtered_keys = {
            self.id_tag,
        }
        if self.post_filtered_tags is not None:
            filtered_keys.update(self.post_filtered_tags)
        post_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        # Rename item
        if new_name is not None:
            post_dict[self.name_tag] = new_name

        return self._update_ids(id_mapping_dict, post_dict)

    def put_data(self, id_mapping_dict):
        """
        Build payload to be used for PUT requests against this config item. From self.data, perform item id
        replacements defined in id_mapping_dict.
        :param id_mapping_dict: {<old item id>: <new item id>} dict. Matches of <old item id> are replaced with
        <new item id>
        :return: Dict containing payload for PUT requests
        """
        return self._update_ids(id_mapping_dict, self.data)

    @staticmethod
    def _update_ids(id_mapping_dict, data_dict):
        def replace_id(match):
            matched_id = match.group(0)
            return id_mapping_dict.get(matched_id, matched_id)

        dict_json = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                           replace_id, json.dumps(data_dict))

        return json.loads(dict_json)

    @property
    def id_references_set(self):
        """
        Return all references to other item ids by this item
        :return: Set containing id-based references
        """
        filtered_keys = {
            self.id_tag,
        }
        filtered_data = {k: v for k, v in self.data.items() if k not in filtered_keys}

        return set(re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                              json.dumps(filtered_data)))


class IndexConfigItem(ConfigItem):
    """
    IndexConfigItem is an index-type ConfigItem that can be iterated over, returning iter_fields
    """
    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item.
        """
        super().__init__(data.get('data') if isinstance(data, dict) else data)

    # Iter_fields should be defined in subclasses and generally follow the format: (<id_tag>, <name_tag>, <ts_tag>)
    iter_fields = None

    store_path = ('index', )

    def __iter__(self):
        return self.iter(*self.iter_fields)

    def iter(self, *iter_fields):
        return map(partial(fields, iter_fields), self.data)


def fields(keys, item):
    return tuple(item[key] for key in keys) if len(keys) > 1 else item[keys[0]]


class CatalogException(Exception):
    """ Exception config item catalog errors """
    pass
