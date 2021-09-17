"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.base.models_base
 This module implements vManage base API models
"""
import json
import re
from os import environ
from pathlib import Path
from itertools import zip_longest
from collections import namedtuple
from typing import Sequence, Dict, Tuple, Union, Iterator, Callable, Mapping, Any
from operator import attrgetter
from requests.exceptions import Timeout
from .rest_api import RestAPIException, Rest


# Top-level directory for local data store
SASTRE_ROOT_DIR = Path(environ.get('SASTRE_ROOT_DIR', Path.cwd()))
DATA_DIR = str(Path(SASTRE_ROOT_DIR, 'data'))


class UpdateEval:
    def __init__(self, data):
        self.is_policy = isinstance(data, list)
        # Master template updates (PUT requests) return a dict containing 'data' key. Non-master templates don't.
        self.is_master = isinstance(data, dict) and 'data' in data

        # This is to homogenize the response payload variants
        self.data = data.get('data') if self.is_master else data

    @property
    def need_reattach(self):
        return not self.is_policy and 'processId' in self.data

    @property
    def need_reactivate(self):
        return self.is_policy and len(self.data) > 0

    def templates_affected_iter(self):
        return iter(self.data.get('masterTemplatesAffected', []))

    def __str__(self):
        return json.dumps(self.data, indent=2)

    def __repr__(self):
        return json.dumps(self.data)


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


class OperationalItem:
    """
    Base class for operational data API elements
    """
    api_path = None
    api_params = None
    fields_std = None
    fields_ext = None
    field_conversion_fns = {}

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.timestamp = payload['header']['generatedOn']

        self._data = payload['data']

        # Some vManage endpoints don't provide all properties in the 'columns' list, which is where 'title' is
        # defined. For those properties without a title, infer one based on the property name.
        self._meta = {attribute_safe(field['property']): field for field in payload['header']['fields']}
        title_dict = {attribute_safe(field['property']): field['title'] for field in payload['header']['columns']}
        for field_property, field in self._meta.items():
            field['title'] = title_dict.get(field_property, field['property'].replace('_', ' ').title())

    @property
    def field_names(self) -> Tuple[str, ...]:
        return tuple(self._meta.keys())

    def field_info(self, *field_names: str, info: str = 'title', default: Union[None, str] = 'N/A') -> tuple:
        """
        Retrieve metadata about one or more fields.
        :param field_names: One or more field name to retrieve metadata from.
        :param info: Indicate which metadata to retrieve. By default, field title is returned.
        :param default: Value to be returned when a field_name does not exist.
        :return: tuple with one or more elements representing the desired metadata for each field requested.
        """
        if len(field_names) == 1:
            return self._meta.get(field_names[0], {}).get(info, default),

        return tuple(entry.get(info, default) for entry in default_getter(*field_names, default={})(self._meta))

    def field_value_iter(self, *field_names: str, **conv_fn_map: Mapping[str, Callable]) -> Iterator[namedtuple]:
        """
        Iterate over entries of a realtime instance. Only fields/columns defined by field_names are yield. Type
        conversion of one or more fields is supported by passing a callable that takes one argument (i.e. the field
        value) and returns the converted value. E.g. passing average_latency=int will convert a string average_latency
        field to an integer.
        :param field_names: Specify one or more field names to retrieve.
        :param conv_fn_map: Keyword arguments passed allow type conversions on fields.
        :return: A FieldValue object (named tuple) with attributes for each field_name.
        """
        FieldValue = namedtuple('FieldValue', field_names)

        def default_conv_fn(field_val):
            return field_val if field_val is not None else ''

        conv_fn_list = [conv_fn_map.get(field_name, default_conv_fn) for field_name in field_names]
        field_properties = self.field_info(*field_names, info='property', default=None)

        def getter_fn(obj):
            return FieldValue._make(
                conv_fn(obj.get(field_property)) if field_property is not None else 'N/A'
                for conv_fn, field_property in zip(conv_fn_list, field_properties)
            )

        return (getter_fn(entry) for entry in self._data)

    @classmethod
    def get(cls, api: Rest, *args, **kwargs):
        try:
            instance = cls.get_raise(api, *args, **kwargs)
            return instance
        except (RestAPIException, Timeout):
            # Timeouts are more common with operational items, while less severe. Capturing here to allow execution to
            # proceed and not fail the whole task
            return None

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        raise NotImplementedError()

    def __str__(self) -> str:
        return json.dumps(self._data, indent=2)

    def __repr__(self) -> str:
        return json.dumps(self._data)


class RealtimeItem(OperationalItem):
    """
    RealtimeItem represents a vManage realtime monitoring API element defined by an ApiPath with a GET path.
    An instance of this class can be created to retrieve and parse realtime endpoints.
    """
    api_params = ('deviceId',)

    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__(payload)

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        params = kwargs or dict(zip(cls.api_params, args))
        return cls(api.get(cls.api_path.get, **params))

    @classmethod
    def is_in_scope(cls, device_model: str) -> bool:
        """
        Indicates whether this RealtimeItem is applicable to a particular device model. Subclasses need to overwrite
        this method when the realtime api endpoint that it represents is specific to certain device models. For instance
        vEdge vs. cEdges.
        """
        return True


class BulkStatsItem(OperationalItem):
    """
    BulkStatsItem represents a vManage bulk statistics API element defined by an ApiPath with a GET path. It supports
    vManage pagination protocol internally, abstracting it from the user.
    An instance of this class can be created to retrieve and parse bulk statistics endpoints.
    """
    api_params = ('endDate', 'startDate', 'count', 'timeZone')
    fields_to_avg = tuple()
    field_node_id = 'vdevice_name'
    field_entry_time = 'entry_time'

    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__(payload)
        self._page_info = payload['pageInfo']

    @property
    def next_page(self) -> Union[str, None]:
        return self._page_info['scrollId'] if self._page_info['hasMoreData'] else None

    def add_payload(self, payload: Mapping[str, Any]) -> None:
        self._data.extend(payload['data'])
        self._page_info = payload['pageInfo']

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        params = kwargs or dict(zip(cls.api_params, args))
        obj = cls(api.get(cls.api_path.get, **params))
        while True:
            next_page = obj.next_page
            if next_page is None:
                break
            payload = api.get(cls.api_path.get, scrollId=next_page)
            obj.add_payload(payload)

        return obj

    @staticmethod
    def time_series_key(sample: namedtuple) -> str:
        """
        Default key used to split a BulkStatsItem into its different time series. Subclasses need to override this as
        needed for the particular endpoint in question
        """
        return sample.vdevice_name

    @staticmethod
    def last_n_secs(n_secs: int, sample_list: Sequence[namedtuple]) -> Iterator[namedtuple]:
        yield sample_list[0]

        oldest_ts = sample_list[0].entry_time - n_secs * 1000
        for sample in sample_list[1:]:
            if sample.entry_time < oldest_ts:
                break
            yield sample

    @staticmethod
    def average_fields(sample_list: Sequence[namedtuple], *fields_to_avg: str) -> dict:
        def average(values):
            avg = sum(values) / len(values)
            # If original values were integer, convert average back to integer
            return round(avg) if isinstance(values[0], int) else avg

        values_get_fn = attrgetter(*fields_to_avg)
        values_iter = (values_get_fn(sample) for sample in sample_list)

        return dict(zip(fields_to_avg, (average(field_samples) for field_samples in zip(*values_iter))))

    def aggregated_value_iter(self, interval_secs: int, *field_names: str,
                              **conv_fn_map: Mapping[str, Callable]) -> Iterator[namedtuple]:
        # Split bulk stats samples into different time series
        time_series_dict = {}
        for sample in self.field_value_iter(self.field_entry_time, *field_names, **conv_fn_map):
            time_series_dict.setdefault(self.time_series_key(sample), []).append(sample)

        # Sort each time series by entry_time with newest samples first
        sort_key = attrgetter(self.field_entry_time)
        for time_series in time_series_dict.values():
            time_series.sort(key=sort_key, reverse=True)

        # Aggregation over newest n samples
        Aggregate = namedtuple('Aggregate', field_names)
        values_get_fn = attrgetter(*field_names)
        fields_to_avg = set(field_names) & set(self.fields_to_avg)
        for time_series_name, time_series in time_series_dict.items():
            if not time_series:
                continue

            series_last_n = list(self.last_n_secs(interval_secs, time_series))
            newest_sample = Aggregate._make(values_get_fn(series_last_n[0]))

            if fields_to_avg:
                yield newest_sample._replace(**self.average_fields(series_last_n, *fields_to_avg))
            else:
                yield newest_sample


class BulkStateItem(OperationalItem):
    """
    BulkStateItem represents a vManage bulk state API element defined by an ApiPath with a GET path. It supports
    vManage pagination protocol internally, abstracting it from the user.
    An instance of this class can be created to retrieve and parse bulk state endpoints.
    """
    api_params = ('count', )
    field_node_id = 'vdevice_name'

    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__(payload)
        self._page_info = payload['pageInfo']

    @property
    def next_page(self) -> Union[str, None]:
        return self._page_info['endId'] if self._page_info['moreEntries'] else None

    def add_payload(self, payload: Mapping[str, Any]) -> None:
        self._data.extend(payload['data'])
        self._page_info = payload['pageInfo']

    @property
    def page_item_count(self) -> int:
        return self._page_info['count']

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        params = kwargs or dict(zip(cls.api_params, args))
        obj = cls(api.get(cls.api_path.get, **params))
        while True:
            next_page = obj.next_page
            if next_page is None:
                break
            payload = api.get(cls.api_path.get, startId=next_page, count=obj.page_item_count)
            obj.add_payload(payload)

        return obj


def attribute_safe(raw_attribute):
    return re.sub(r'[^a-zA-Z0-9_]', '_', raw_attribute)


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

    @classmethod
    def get(cls, api, *path_entries):
        try:
            return cls.get_raise(api, *path_entries)
        except RestAPIException:
            return None

    @classmethod
    def get_raise(cls, api, *path_entries):
        return cls(api.get(cls.api_path.get, *path_entries))

    def __str__(self):
        return json.dumps(self.data, indent=2)

    def __repr__(self):
        return json.dumps(self.data)


class IndexApiItem(ApiItem):
    """
    IndexApiItem is an index-type ApiItem that can be iterated over, returning iter_fields
    """
    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this API item.
        """
        super().__init__(data.get('data') if isinstance(data, dict) else data)

    # Iter_fields should be defined in subclasses and needs to be a tuple subclass.
    iter_fields = None
    # Extended_iter_fields should be defined in subclasses that use extended_iter, needs to be a tuple subclass.
    extended_iter_fields = None

    def __iter__(self):
        return self.iter(*self.iter_fields)

    def iter(self, *iter_fields):
        return (default_getter(*iter_fields)(elem) for elem in self.data)

    def extended_iter(self, default=None):
        """
        Returns an iterator where each entry is composed of the combined fields of iter_fields and extended_iter_fields.
        None is returned on any fields that are missing in an entry
        :param default: Value to return when a field does not exist
        :return: The iterator
        """
        return (default_getter(*self.iter_fields, *self.extended_iter_fields, default=default)(elem)
                for elem in self.data)


class ConfigItem(ApiItem):
    """
    ConfigItem is an ApiItem that can be backed up and restored
    """
    store_path = None
    store_file = None
    root_dir = DATA_DIR
    factory_default_tag = 'factoryDefault'
    readonly_tag = 'readOnly'
    owner_tag = 'owner'
    info_tag = 'infoTag'
    type_tag = None
    post_filtered_tags = None
    skip_cmp_tag_set = set()
    name_check_regex = re.compile(r'(?=^.{1,128}$)[^&<>! "]+$')

    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item
        """
        super().__init__(data)

    def is_equal(self, other):
        local_cmp_dict = {k: v for k, v in self.data.items() if k not in self.skip_cmp_tag_set | {self.id_tag}}
        other_cmp_dict = {k: v for k, v in other.items() if k not in self.skip_cmp_tag_set | {self.id_tag}}

        return sorted(json.dumps(local_cmp_dict)) == sorted(json.dumps(other_cmp_dict))

    @property
    def is_readonly(self):
        return self.data.get(self.factory_default_tag, False) or self.data.get(self.readonly_tag, False)

    @property
    def is_system(self):
        return self.data.get(self.owner_tag, '') == 'system' or self.data.get(self.info_tag, '') == 'aci'

    @property
    def type(self):
        return self.data.get(self.type_tag)

    @classmethod
    def get_filename(cls, ext_name, item_name, item_id):
        if item_name is None or item_id is None:
            # Assume store_file does not have variables
            return cls.store_file

        safe_name = filename_safe(item_name) if not ext_name else '{name}_{uuid}'.format(name=filename_safe(item_name),
                                                                                         uuid=item_id)
        return cls.store_file.format(item_name=safe_name, item_id=item_id)

    @classmethod
    def load(cls, node_dir, ext_name=False, item_name=None, item_id=None, raise_not_found=False, use_root_dir=True):
        """
        Factory method that loads data from a json file and returns a ConfigItem instance with that data

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        :param item_name: (Optional) Name of the item being loaded. Variable used to build the filename.
        :param item_id: (Optional) UUID for the item being loaded. Variable used to build the filename.
        :param raise_not_found: (Optional) If set to True, raise FileNotFoundError if file is not found.
        :param use_root_dir: True indicates that node_dir is under the root_dir. When false, item should be located
                             directly under node_dir/store_path
        :return: ConfigItem object, or None if file does not exist and raise_not_found=False
        """
        dir_path = Path(cls.root_dir, node_dir, *cls.store_path) if use_root_dir else Path(node_dir, *cls.store_path)
        file_path = dir_path.joinpath(cls.get_filename(ext_name, item_name, item_id))
        try:
            with open(file_path, 'r') as read_f:
                data = json.load(read_f)
        except FileNotFoundError:
            if raise_not_found:
                has_detail = item_name is not None and item_id is not None
                detail = f': {item_name}, {item_id}' if has_detail else ''
                raise FileNotFoundError(f'{cls.__name__} file not found{detail}') from None
            return None
        except json.decoder.JSONDecodeError as ex:
            raise ModelException(f'Invalid JSON file: {file_path}: {ex}') from None
        else:
            return cls(data)

    def save(self, node_dir, ext_name=False, item_name=None, item_id=None):
        """
        Save data (i.e. self.data) to a json file

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        :param item_name: (Optional) Name of the item being saved. Variable used to build the filename.
        :param item_id: (Optional) UUID for the item being saved. Variable used to build the filename.
        :return: True indicates data has been saved. False indicates no data to save (and no file has been created).
        """
        if self.is_empty:
            return False

        dir_path = Path(self.root_dir, node_dir, *self.store_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        with open(dir_path.joinpath(self.get_filename(ext_name, item_name, item_id)), 'w') as write_f:
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
            '@rid',
            'createdOn',
            'lastUpdatedOn'
        }
        if self.post_filtered_tags is not None:
            filtered_keys.update(self.post_filtered_tags)
        post_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        # Rename item
        if new_name is not None:
            post_dict[self.name_tag] = new_name

        return update_ids(id_mapping_dict, post_dict)

    def put_data(self, id_mapping_dict):
        """
        Build payload to be used for PUT requests against this config item. From self.data, perform item id
        replacements defined in id_mapping_dict.
        :param id_mapping_dict: {<old item id>: <new item id>} dict. Matches of <old item id> are replaced with
        <new item id>
        :return: Dict containing payload for PUT requests
        """
        filtered_keys = {
            '@rid',
            'createdOn',
            'lastUpdatedOn'
        }
        put_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        return update_ids(id_mapping_dict, put_dict)

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

    def get_new_name(self, name_template: str) -> Tuple[str, bool]:
        """
        Return a new valid name for this item based on the format string template provided. Variable {name} is replaced
        with the existing item name. Other variables are provided via kwargs.
        :param name_template: str containing the name template to construct the new name.
                              For example: migrated_{name&G_Branch_184_(.*)}
        :return: Tuple containing new name and an indication whether it is valid
        """
        is_valid = False

        try:
            new_name = ExtendedTemplate(name_template)(self.data[self.name_tag])
        except KeyError:
            new_name = None
        else:
            if self.name_check_regex.search(new_name) is not None:
                is_valid = True

        return new_name, is_valid

    def find_key(self, key, from_key=None):
        """
        Returns a list containing the values of all occurrences of key inside data. Matched values that are dict or list
        are not included.
        :param key: Key to search
        :param from_key: Top-level key under which to start the search
        :return: List
        """
        match_list = []

        def find_in(json_obj):
            if isinstance(json_obj, dict):
                matched_val = json_obj.get(key)
                if matched_val is not None and not isinstance(matched_val, dict) and not isinstance(matched_val, list):
                    match_list.append(matched_val)
                for value in json_obj.values():
                    find_in(value)

            elif isinstance(json_obj, list):
                for elem in json_obj:
                    find_in(elem)

            return match_list

        return find_in(self.data) if from_key is None else find_in(self.data[from_key])


# Used for IndexConfigItem iter_fields when they follow (<item-id-label>, <item-name-label>) format
IdName = namedtuple('IdName', ['id', 'name'])


class IndexConfigItem(ConfigItem):
    """
    IndexConfigItem is an index-type ConfigItem that can be iterated over, returning iter_fields
    """
    def __init__(self, data):
        """
        :param data: dict containing the information to be associated with this configuration item.
        """
        super().__init__(data.get('data') if isinstance(data, dict) else data)

        # When iter_fields is a regular tuple, it is completely opaque. However, if it is an IdName, then it triggers
        # an evaluation of whether there is collision amongst the filename_safe version of all names in this index.
        # need_extended_name = True indicates that there is collision and that extended names should be used when
        # saving/loading to/from backup
        if isinstance(self.iter_fields, IdName):
            filename_safe_set = {filename_safe(item_name, lower=True) for item_name in self.iter(self.iter_fields.name)}
            self.need_extended_name = len(filename_safe_set) != len(self.data)
        else:
            self.need_extended_name = False

    # Iter_fields should be defined in subclasses and needs to be a tuple subclass.
    # When it follows the format (<item-id>, <item-name>), use an IdName namedtuple instead of regular tuple.
    iter_fields = None
    # Extended_iter_fields should be defined in subclasses that use extended_iter, needs to be a tuple subclass.
    extended_iter_fields = None

    store_path = ('inventory', )

    @classmethod
    def create(cls, item_list: Sequence[ConfigItem], id_hint_dict: Dict[str, str]):
        def item_dict(item_obj: ConfigItem):
            return {
                key: item_obj.data.get(key, id_hint_dict.get(item_obj.name)) for key in cls.iter_fields
            }

        index_dict = {
            'data': [item_dict(item) for item in item_list]
        }
        return cls(index_dict)

    def __iter__(self):
        return self.iter(*self.iter_fields)

    def iter(self, *iter_fields):
        return (default_getter(*iter_fields)(elem) for elem in self.data)

    def extended_iter(self, default=None):
        """
        Returns an iterator where each entry is composed of the combined fields of iter_fields and extended_iter_fields.
        None is returned on any fields that are missing in an entry
        :param default: Value to return when a field does not exist
        :return: The iterator
        """
        return (default_getter(*self.iter_fields, *self.extended_iter_fields, default=default)(elem)
                for elem in self.data)


class ServerInfo:
    root_dir = DATA_DIR
    store_file = 'server_info.json'

    def __init__(self, **kwargs):
        """
        :param kwargs: key-value pairs of information about the vManage server
        """
        self.data = kwargs

    def __getattr__(self, item):
        attr = self.data.get(item)
        if attr is None:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{item}'")
        return attr

    @classmethod
    def load(cls, node_dir):
        """
        Factory method that loads data from a json file and returns a ServerInfo instance with that data

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :return: ServerInfo object, or None if file does not exist
        """
        dir_path = Path(cls.root_dir, node_dir)
        file_path = dir_path.joinpath(cls.store_file)
        try:
            with open(file_path, 'r') as read_f:
                data = json.load(read_f)
        except FileNotFoundError:
            return None
        except json.decoder.JSONDecodeError as ex:
            raise ModelException(f"Invalid JSON file: {file_path}: {ex}") from None
        else:
            return cls(**data)

    def save(self, node_dir):
        """
        Save data (i.e. self.data) to a json file

        :param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        :return: True indicates data has been saved. False indicates no data to save (and no file has been created).
        """
        dir_path = Path(self.root_dir, node_dir)
        dir_path.mkdir(parents=True, exist_ok=True)

        with open(dir_path.joinpath(self.store_file), 'w') as write_f:
            json.dump(self.data, write_f, indent=2)

        return True


def filename_safe(name: str, lower: bool = False) -> str:
    """
    Perform the necessary replacements in <name> to make it filename safe.
    Any char that is not a-z, A-Z, 0-9, '_', ' ', or '-' is replaced with '_'. Convert to lowercase, if lower=True.
    :param lower: If True, apply str.lower() to result.
    :param name: name string to be converted
    :return: string containing the filename-save version of item_name
    """
    # Inspired by Django's slugify function
    cleaned = re.sub(r'[^\w\s-]', '_', name)
    return cleaned.lower() if lower else cleaned


def update_ids(id_mapping_dict, item_data):
    def replace_id(match):
        matched_id = match.group(0)
        return id_mapping_dict.get(matched_id, matched_id)

    dict_json = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                       replace_id, json.dumps(item_data))

    return json.loads(dict_json)


class ExtendedTemplate:
    template_pattern = re.compile(r'{name(?:\s+(?P<regex>.*?))?}')

    def __init__(self, template):
        self.src_template = template
        self.label_value_map = None

    def __call__(self, name):
        def regex_replace(match_obj):
            regex = match_obj.group('regex')
            if regex is not None:
                regex_p = re.compile(regex)
                if not regex_p.groups:
                    raise KeyError('regular expression must include at least one capturing group')

                value, regex_p_subs = regex_p.subn(''.join(f'\\{group+1}' for group in range(regex_p.groups)), name)
                new_value = value if regex_p_subs else ''
            else:
                new_value = name

            label = 'name_{count}'.format(count=len(self.label_value_map))
            self.label_value_map[label] = new_value

            return f'{{{label}}}'

        self.label_value_map = {}
        template, name_p_subs = self.template_pattern.subn(regex_replace, self.src_template)
        if not name_p_subs:
            raise KeyError('template must include {name} variable')

        return template.format(**self.label_value_map)


def default_getter(*fields, default=None):
    if len(fields) == 1:
        def getter_fn(obj):
            return obj.get(fields[0], default)
    else:
        def getter_fn(obj):
            return tuple(obj.get(field, default) for field in fields)

    return getter_fn


class ModelException(Exception):
    """ Exception for REST API model errors """
    pass
