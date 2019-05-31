import os.path
import json
from functools import partial
from collections import namedtuple


# Each entry in _catalog is a tuple (<tag>, <title>, <index_cls>, <handler_cls>)
_catalog = list()

CatalogEntry = namedtuple('CatalogEntry', ['tag', 'title', 'index_cls', 'handler_cls'])

CATALOG_TAG_ALL = 'all'


def register(tag, title, handler_cls):
    """
    Decorator used for registering config item index/handler classes with the catalog.
    The class being decorated needs to be a subclass of IndexConfigItem.
    :param tag: Tag string associated with this item. String 'all' is reserved and cannot be used.
    :param title: Item title used for logging purposes
    :param handler_cls: The config item handler class, needs to be a subclass of ConfigItem
    :return: decorator
    """
    def decorator(index_cls):
        if not isinstance(index_cls, type) or not issubclass(index_cls, IndexConfigItem):
            raise CatalogException('Attempt to register an invalid config item index class: {}'.format(index_cls.__name__))

        if not isinstance(handler_cls, type) or not issubclass(handler_cls, ConfigItem):
            raise CatalogException('Attempt to register an invalid config item class with {}: {}'.format(index_cls.__name__, handler_cls.__name__))

        if not isinstance(tag, str) or tag.lower() == CATALOG_TAG_ALL:
            raise CatalogException('Invalid tag provided for class {}: {}'.format(index_cls.__name__, tag))

        _catalog.append(CatalogEntry(tag, title, index_cls, handler_cls))

        return index_cls

    return decorator


def catalog_size():
    """
    Return number of entries in the catalog
    :return: integer
    """
    return len(_catalog)


def catalog_items(*tags):
    """
    Return an iterator of catalog items matching the specified tag
    :param tags:
    :return:
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


# (<level_key>, <id_key>)
RefInfo = namedtuple('RefInfo', ['level_key', 'id_key'])

ApiPath = namedtuple('ApiPath', ['get', 'post', 'put', 'delete'])


class ConfigItem:
    api_path = None
    store_path = None
    store_file = None

    id_tag = None
    name_tag = None

    # Information used to figure out dependencies between ConfigItems.
    # It is a tuple containing one or more RefInfo tuples
    dependency_info = tuple()

    root_dir = 'data'

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item
        """
        self.data = data

    @staticmethod
    def reference_ids(level_dict, level_dep_info):
        id_set = set()

        if len(level_dep_info) > 0:
            for reference_entry in level_dict.get(level_dep_info[0].level_key, []):
                reference_id = reference_entry.get(level_dep_info[0].id_key)
                if reference_id is not None:
                    id_set.add(reference_id)

                id_set.update(ConfigItem.reference_ids(reference_entry, level_dep_info[1:]))

        return id_set

    def get_dependencies(self):
        return ConfigItem.reference_ids(self.data, self.dependency_info)

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

    def get_id(self):
        return self.data[self.id_tag] if self.id_tag is not None else None

    def get_name(self):
        return self.data[self.name_tag] if self.name_tag is not None else None

    @property
    def post_data(self):
        filtered_keys = {
            self.id_tag,
        }
        post_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        post_dict[self.name_tag] = 'test_{}'.format(post_dict[self.name_tag])

        return post_dict

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
