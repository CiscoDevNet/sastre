"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.base.models_base
 This module implements vManage base API models
"""
import json
import re
from os import environ
from pathlib import Path
from itertools import zip_longest
from collections import namedtuple
from typing import Sequence, Tuple, Union, Iterator, Callable, Mapping, Any, Optional, Dict, List, Generator, NamedTuple
from operator import attrgetter
from datetime import datetime, timezone
from urllib.parse import quote_plus
from pydantic import BaseModel, Extra
from requests.exceptions import Timeout
from .rest_api import RestAPIException, Rest

# Top-level directory for local data store
SASTRE_ROOT_DIR = Path(environ.get('SASTRE_ROOT_DIR', Path.cwd()))
DATA_DIR = str(Path(SASTRE_ROOT_DIR, 'data'))


# Used for IndexConfigItem iter_fields when they follow (<item-id-label>, <item-name-label>) format
IdName = namedtuple('IdName', ['id', 'name'])


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
    __slots__ = ('path_vars', 'get', 'post', 'put', 'delete')

    def __init__(self, get: Optional[str], *other_ops: Optional[str],
                 path_vars: Optional[Sequence[str]] = None) -> None:
        """
        @param get: URL path for get operations
        @param other_ops: URL path for post, put and delete operations, in this order. If an item is not specified
                          the same URL as the last operation provided is used.
        @param path_vars: Path variable names that may be present in defined paths. It is assumed that all methods have
                          the same path variables.
        """
        self.get = get
        last_op = other_ops[-1] if other_ops else get
        for field, value in zip_longest(self.__slots__[2:], other_ops, fillvalue=last_op):
            setattr(self, field, value)

        if path_vars is None:
            for value in (getattr(self, field) for field in self.__slots__[1:]):
                if value is not None:
                    # The first valid path becomes the reference to discover path variables
                    self.path_vars = ApiPath.discover_path_vars(value)
                    break
            else:
                self.path_vars = None
        else:
            self.path_vars = tuple(path_vars)

    def resolve(self, *var_values: str, **var_mappings: str) -> 'ApiPath':
        """
        Resolve an API Path containing path variables (ex. /v1/config/{config_id}/etc) into a concrete API path with
        path variables replaced with their values, as provided via var_values or var_mappings.
        @param var_values: Values for path variables, in the same order in which they are defined.
        @param var_mappings: Key-value pairs associating values to path variable names.
        @return: A new ApiPath instance containing path variables replaced with their values.
        """
        if not self.path_vars:
            return self

        if not var_mappings and len(self.path_vars) != len(var_values):
            raise ValueError(f"Unexpected var values provided: {', '.join(var_values) or 'None provided'} [{self}]")
        if not var_values and set(self.path_vars) != var_mappings.keys():
            raise ValueError(f"Unexpected var mappings provided: {', '.join(var_mappings) or 'None provided'} [{self}]")

        var_bindings = var_mappings or dict(zip(self.path_vars, var_values))
        # Ensure provided values are url-safe
        var_bindings = {name: quote_plus(value) for name, value in var_bindings.items()}

        def resolve_path(field):
            path = getattr(self, field)
            return path.format(**var_bindings) if path is not None else None

        return ApiPath(*tuple(resolve_path(field) for field in self.__slots__[1:]))

    def __repr__(self) -> str:
        path_vars = f", path_vars=[{', '.join(self.path_vars)}]" if self.path_vars else ""
        return f"{self.__class__.__name__}({self.get}, {self.post}, {self.put}, {self.delete}{path_vars})"

    @staticmethod
    def discover_path_vars(path_template: str) -> tuple:
        # If no path variable is discovered an empty tuple is returned
        return tuple(m.group(1) for m in re.finditer(r'{\s*([^}]+)\s*}', path_template))


class CliOrFeatureApiPath:
    def __init__(self, api_path_feature, api_path_cli):
        self.api_path_feature = api_path_feature
        self.api_path_cli = api_path_cli

    def __get__(self, instance, owner):
        # If called from class, assume it is a feature template
        is_cli_template = instance is not None and instance.is_type_cli

        return self.api_path_cli if is_cli_template else self.api_path_feature


class PathKey(NamedTuple):
    """
    PathKey tuples are used to lookup api paths in ApiPathGroup
    """
    parcel_type: str
    parent_parcel_type: Optional[str] = None


class ApiPathGroup:
    """
    ApiPathGroup is used on feature profiles and contains mapping of parcelType to ApiPath. ApiPaths relative to parcel
    references are registered using the optional parcel_reference_path_map.
    """
    def __init__(self, path_map: Mapping[str, ApiPath],
                 parcel_reference_path_map: Optional[Mapping[PathKey, ApiPath]] = None) -> None:
        """
        @param path_map: Register parcel ApiPaths to a feature profile. Mapping of {<parcelType>: ApiPath, ... }
        @param parcel_reference_path_map: Register parcel reference ApiPaths to a feature profile. Mapping of
                                          {PathKey(<ParcelType>, <parent ParcelType>): ApiPath, ...}
        """
        self._path_map = dict(path_map)
        self._parcel_ref_map = dict(parcel_reference_path_map) if parcel_reference_path_map is not None else {}
        self._referenced_types = set(path_key.parcel_type for path_key in self._parcel_ref_map)

    def api_path(self, key: PathKey) -> Tuple[Union[ApiPath, None], bool]:
        """
        Returns the api path associated with the provided key, along with whether this is a parcel reference or an
        actual parcel.
        @param key: A PathKey to find the api path
        @return: (<parcel api path>, <is reference>) tuple
        """
        parcel_reference_path = self._parcel_ref_map.get(key)
        if parcel_reference_path is not None:
            return parcel_reference_path, True

        return self._path_map.get(key.parcel_type), False

    def is_referenced_type(self, parcel_type: str) -> bool:
        """
        Indicates whether the provided parcel_type is a type that can be referenced
        @param parcel_type: Parcel type
        @return: True if this parcel type is one that can be referenced, False otherwise
        """
        return parcel_type in self._referenced_types


class OperationalItem:
    """
    Base class for operational data API elements
    """
    api_path = None
    api_params = None
    fields_std = None  # Tuple with standard fields to include (by default) as entries are iterated
    fields_ext = None  # Tuple with extended fields to add, on top of fields_std
    fields_sub = None  # Tuple containing fields to subtract from fields_std as entries are iterated
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
        @param field_names: One or more field name to retrieve metadata from.
        @param info: Indicate which metadata to retrieve. By default, field title is returned.
        @param default: Value to be returned when a field_name does not exist.
        @return: tuple with one or more elements representing the desired metadata for each field requested.
        """
        if len(field_names) == 1:
            return self._meta.get(field_names[0], {}).get(info, default),

        return tuple(entry.get(info, default) for entry in default_getter(*field_names, default={})(self._meta))

    def field_value_iter(self, *field_names: str, **conv_fn_map: Mapping[str, Callable]) -> Iterator[namedtuple]:
        """
        Iterate over entries of an operational item instance. Only fields/columns defined by field_names are yield.
        Type conversion of one or more fields is supported by passing a callable that takes one argument (i.e. the field
        value) and returns the converted value. E.g. passing average_latency=int will convert a string average_latency
        field to an integer.
        @param field_names: Specify one or more field names to retrieve.
        @param conv_fn_map: Keyword arguments passed allow type conversions on fields.
        @return: A FieldValue object (named tuple) with attributes for each field_name.
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
        """
        Iterate over aggregated values off the different time series from this BulkStatsItem. Time series are identified
        using time_series_key.

        Aggregation is performed as follows:
        - Fields in field_names that are in self.fields_to_avg are averaged over interval_secs.
        - For remaining fields, the newest sample is used.

        @param interval_secs: Interval to aggregate samples.
        @param field_names: Desired field names to return on each iteration
        @param conv_fn_map: Conversion functions to be applied on fields, before they are aggregated.
        @return: Iterator of namedtuple, each instance corresponding to a time series.
        """
        # Split bulk stats samples into different time series
        time_series_dict = {}
        for sample in self.field_value_iter(self.field_entry_time, *field_names, **conv_fn_map):
            time_series_dict.setdefault(self.time_series_key(sample), []).append(sample)

        # Sort each time series by entry_time with the newest samples first
        sort_key = attrgetter(self.field_entry_time)
        for time_series in time_series_dict.values():
            time_series.sort(key=sort_key, reverse=True)

        # Aggregation over newest n samples
        Aggregate = namedtuple('Aggregate', field_names)
        values_get_fn = attrgetter(*field_names)
        fields_to_avg = set(field_names) & set(self.fields_to_avg)
        for time_series in time_series_dict.values():
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
    api_params = ('count',)
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


def entry_time_parse(timestamp: str) -> datetime:
    return datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc)


class RecordItem(OperationalItem):
    # Datetime string format used in log item queries
    TIME_FORMAT = "%Y-%m-%dT%H:%M:%S %Z"
    QUERY_SIZE_MAX = 10000

    def __init__(self, payload: Mapping[str, Any]) -> None:
        super().__init__(payload)
        self._page_info = payload['pageInfo']

    @staticmethod
    def query(start_time: datetime, end_time: datetime, size: int) -> Dict[str, Any]:
        """
        @param start_time: Starting date time for the query, i.e. oldest.
        @param end_time: End date time for the query, i.e. newest.
        @param size: Number of records to return. Positive integer.
        @return: Query payload used to retrieve log items
        """
        return {
            "size": RecordItem.QUERY_SIZE_MAX if size > RecordItem.QUERY_SIZE_MAX else size,
            "query": {
                "condition": "AND",
                "rules": [
                    {
                        "field": "entry_time",
                        "type": "date",
                        "value": [
                            start_time.strftime(RecordItem.TIME_FORMAT),
                            end_time.strftime(RecordItem.TIME_FORMAT)
                        ],
                        "operator": "between"
                    }
                ]
            },
            "sort": [
                {
                    "field": "entry_time",
                    "type": "date",
                    "order": "desc"
                }
            ]
        }

    @property
    def next_page(self) -> Union[datetime, None]:
        if 'endTime' not in self._page_info or self.page_item_count < RecordItem.QUERY_SIZE_MAX:
            return None

        # endTime is provided as string in timestamp format
        return entry_time_parse(self._page_info['endTime'])

    def add_payload(self, payload: Mapping[str, Any]) -> None:
        self._data.extend(payload['data'])
        self._page_info = payload['pageInfo']

    @property
    def page_item_count(self) -> int:
        return self._page_info['count']

    @classmethod
    def get_raise(cls, api: Rest, *, start_time: datetime = None, end_time: datetime = None, max_records: int = 0):
        obj = cls(api.post(cls.query(start_time, end_time, max_records), cls.api_path.post))
        while True:
            next_page = obj.next_page
            if next_page is None:
                break

            payload = api.post(cls.query(start_time, next_page, max_records - len(obj._data)), cls.api_path.post)
            obj.add_payload(payload)

        return obj


def attribute_safe(raw_attribute):
    return re.sub(r'\W', '_', raw_attribute, flags=re.ASCII)


class ApiItem:
    """
    ApiItem represents a vManage API element defined by an ApiPath with GET, POST, PUT and DELETE paths. An instance
    of this class can be created to store the contents of that vManage API element (self.data field).
    """
    api_path = None  # An ApiPath instance
    id_tag = None
    name_tag = None

    def __init__(self, data):
        """
        @param data: dict containing the information to be associated with this api item
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
    def get(cls, api: Rest, *args, **kwargs):
        try:
            return cls.get_raise(api, *args, **kwargs)
        except RestAPIException:
            return None

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        # Extract path vars from kwargs, what is left becomes query vars
        path_vars_map = {}
        if cls.api_path.path_vars is not None:
            for path_var in cls.api_path.path_vars:
                path_var_value = kwargs.pop(path_var, None)
                if path_var_value is not None:
                    path_vars_map[path_var] = path_var_value

        return cls(api.get(cls.api_path.resolve(**path_vars_map).get, *args, **kwargs))

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
        @param data: dict containing the information to be associated with this API item.
        """
        super().__init__(data.get('data') if isinstance(data, dict) else data)

    # Iter_fields should be defined in subclasses and needs to be a tuple subclass.
    iter_fields = None
    # Extended_iter_fields should be defined in subclasses that use extended_iter, needs to be a tuple subclass.
    extended_iter_fields = None

    def iter(self, *iter_fields: str, default: Any = None) -> Iterator:
        """
        Returns an iterator where each entry is the value of the respective field in iter_fields.
        @param default: Value to return for any field missing in an entry. Default is None.
        @return: Iterator of entries in the index object
        """
        return (default_getter(*iter_fields, default=default)(entry) for entry in self.data)

    def __iter__(self):
        return self.iter(*self.iter_fields)

    def extended_iter(self, default=None) -> Iterator:
        """
        Returns an iterator where each entry is composed of the combined fields of iter_fields and extended_iter_fields.
        None is returned on any fields that are missing in an entry
        @param default: Value to return for any field missing in an entry. Default is None.
        @return: Iterator of entries in the index object
        """
        return self.iter(*self.iter_fields, *self.extended_iter_fields, default=default)


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

    def is_equal(self, other_payload: Dict[str, Any]) -> bool:
        exclude_set = self.skip_cmp_tag_set | {self.id_tag}

        local_cmp_dict = {k: v for k, v in self.data.items() if k not in exclude_set}
        other_cmp_dict = {k: v for k, v in other_payload.items() if k not in exclude_set}

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

        @param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        @param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        @param item_name: (Optional) Name of the item being loaded. Variable used to build the filename.
        @param item_id: (Optional) UUID for the item being loaded. Variable used to build the filename.
        @param raise_not_found: (Optional) If set to True, raise FileNotFoundError if file is not found.
        @param use_root_dir: True indicates that node_dir is under the root_dir. When false, item should be located
                             directly under node_dir/store_path
        @return: ConfigItem object, or None if file does not exist and raise_not_found=False
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

        @param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        @param ext_name: True indicates that item_names need to be extended (with item_id) in order to make their
                         filename safe version unique. False otherwise.
        @param item_name: (Optional) Name of the item being saved. Variable used to build the filename.
        @param item_id: (Optional) UUID for the item being saved. Variable used to build the filename.
        @return: True indicates data has been saved. False indicates no data to save (and no file has been created).
        """
        if self.is_empty:
            return False

        dir_path = Path(self.root_dir, node_dir, *self.store_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        with open(dir_path.joinpath(self.get_filename(ext_name, item_name, item_id)), 'w') as write_f:
            json.dump(self.data, write_f, indent=2)

        return True

    def post_data(self, id_mapping_dict: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """
        Build payload to be used for POST requests against this config item. From "self.data", perform item id
        replacements defined in id_mapping_dict, also remove item id and rename item with new_name (if provided).
        @param id_mapping_dict: {<old item id>: <new item id>} dict. If provided, <old item id> matches are replaced
                                with <new item id>
        @return: Dict containing payload for POST requests
        """
        # Delete keys that shouldn't be on post requests
        filtered_keys = {
            self.id_tag,
            '@rid',
            'createdBy',
            'createdOn',
            'lastUpdatedBy',
            'lastUpdatedOn'
        }
        if self.post_filtered_tags is not None:
            filtered_keys.update(self.post_filtered_tags)
        post_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        # Clear read-only flags
        if post_dict.get(self.factory_default_tag, False):
            post_dict[self.factory_default_tag] = False
        if post_dict.get(self.readonly_tag, False):
            post_dict[self.readonly_tag] = False

        if id_mapping_dict is None:
            return post_dict

        return update_ids(id_mapping_dict, post_dict)

    def put_data(self, id_mapping_dict: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """
        Build payload to be used for PUT requests against this config item. From "self.data", perform item id
        replacements defined in id_mapping_dict.
        @param id_mapping_dict: {<old item id>: <new item id>} dict. If provided, <old item id> matches are replaced
                                with <new item id>
        @return: Dict containing payload for PUT requests
        """
        filtered_keys = {
            '@rid',
            'createdBy',
            'createdOn',
            'lastUpdatedBy',
            'lastUpdatedOn'
        }
        put_dict = {k: v for k, v in self.data.items() if k not in filtered_keys}

        if id_mapping_dict is None:
            return put_dict

        return update_ids(id_mapping_dict, put_dict)

    @property
    def id_references_set(self):
        """
        Return all references to other item ids by this item
        @return: Set containing id-based references
        """
        filtered_keys = {
            self.id_tag,
        }
        filtered_data = {k: v for k, v in self.data.items() if k not in filtered_keys}

        return set(re.findall(r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}',
                              json.dumps(filtered_data)))

    @classmethod
    def is_name_valid(cls, proposed_name: Optional[str]) -> bool:
        return proposed_name is not None and cls.name_check_regex.search(proposed_name) is not None

    def find_key(self, key, from_key=None):
        """
        Returns a list containing the values of all occurrences of key inside data. Matched values that are dict or list
        are not included.
        @param key: Key to search
        @param from_key: Top-level key under which to start the search
        @return: List
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


class IndexConfigItem(ConfigItem):
    """
    IndexConfigItem is an index-type ConfigItem that can be iterated over, returning iter_fields
    """

    def __init__(self, data):
        """
        @param data: dict containing the information to be associated with this configuration item.
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

    store_path = ('inventory',)

    @classmethod
    def create(cls, item_list: Sequence[ConfigItem], id_hint_dict: Mapping[str, str]):
        def index_entry_dict(item_obj: ConfigItem):
            return {
                key: item_obj.data.get(key, id_hint_dict.get(item_obj.name)) for key in cls.iter_fields
            }

        index_payload = {
            'data': [index_entry_dict(item) for item in item_list]
        }
        return cls(index_payload)

    def iter(self, *iter_fields: str, default: Any = None) -> Iterator:
        """
        Returns an iterator where each entry is the value of the respective field in iter_fields.
        @param default: Value to return for any field missing in an entry. Default is None.
        @return: Iterator of entries in the index object
        """
        return (default_getter(*iter_fields, default=default)(entry) for entry in self.data)

    def __iter__(self):
        return self.iter(*self.iter_fields)

    def extended_iter(self, default=None) -> Iterator:
        """
        Returns an iterator where each entry is composed of the combined fields of iter_fields and extended_iter_fields.
        None is returned on any fields that are missing in an entry
        @param default: Value to return for any field missing in an entry. Default is None.
        @return: Iterator of entries in the index object
        """
        return self.iter(*self.iter_fields, *self.extended_iter_fields, default=default)


class ConfigRequestModel(BaseModel):
    class Config:
        extra = Extra.ignore


class FeatureProfileModel(ConfigRequestModel):
    name: str
    description: str

    # In 20.8.1 get profile contains 'profileName', while post/put requests require 'name' instead
    def __init__(self, **kwargs):
        name = kwargs.pop('name', None) or kwargs.pop('profileName', None)
        if name is not None:
            kwargs['name'] = name
        super().__init__(**kwargs)


class ProfileParcelPayloadModel(ConfigRequestModel):
    name: str
    description: str = ''
    data: Dict[str, Any]


class ProfileParcelModel(ConfigRequestModel):
    parcelId: str
    parcelType: str
    payload: ProfileParcelPayloadModel
    subparcels: List['ProfileParcelModel']


class ProfileParcelReferenceModel(ConfigRequestModel):
    parcelId: str


class Config2Item(ConfigItem):
    """
    Config2Item is a specialized ConfigItem to support vManage Config 2.0 elements

    """
    post_model: Callable[..., ConfigRequestModel] = None
    put_model: Optional[Callable[..., ConfigRequestModel]] = None
    delete_model: Optional[Callable[..., ConfigRequestModel]] = None

    def is_equal(self, other: Dict[str, Any]) -> bool:
        exclude_set = self.skip_cmp_tag_set | {self.id_tag}
        put_model = self.put_model or self.post_model

        local_cmp_dict = put_model(**self.data).dict(by_alias=True, exclude=exclude_set)
        other_cmp_dict = {k: v for k, v in other.items() if k not in exclude_set}

        return sorted(json.dumps(local_cmp_dict)) == sorted(json.dumps(other_cmp_dict))

    def post_data(self, id_mapping_dict: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """
        Build payload to be used for POST requests against this config item. From "self.data", perform item id
        replacements defined in id_mapping_dict, also remove item id and rename item with new_name (if provided).
        @param id_mapping_dict: {<old item id>: <new item id>} dict. If provided, <old item id> matches are replaced
                                with <new item id>
        @return: Dict containing payload for POST requests
        """
        return self._op_data(self.post_model, id_mapping_dict)

    def put_data(self, id_mapping_dict: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """
        Build payload to be used for PUT requests against this config item. From "self.data", perform item id
        replacements defined in id_mapping_dict.
        @param id_mapping_dict: {<old item id>: <new item id>} dict. If provided, <old item id> matches are replaced
                                with <new item id>
        @return: Dict containing payload for PUT requests
        """
        put_model = self.put_model or self.post_model
        return self._op_data(put_model, id_mapping_dict)

    def delete_data(self, id_mapping_dict: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        """
        Build payload to be used for DELETE requests against this config item. From "self.data", perform item id
        replacements defined in id_mapping_dict.
        @param id_mapping_dict: {<old item id>: <new item id>} dict. If provided, <old item id> matches are replaced
                                with <new item id>
        @return: Dict containing payload for DELETE requests
        """
        delete_model = self.delete_model or self.put_model or self.post_model
        return self._op_data(delete_model, id_mapping_dict)

    def _op_data(self, op_model: Callable[..., ConfigRequestModel],
                 id_mapping_dict: Optional[Mapping[str, str]]) -> Dict[str, Any]:
        payload = op_model(**self.data)

        if id_mapping_dict is None:
            return payload.dict(by_alias=True)

        return update_ids(id_mapping_dict, payload.dict(by_alias=True))


class FeatureProfile(Config2Item):
    store_file = '{item_name}.json'
    id_tag = 'profileId'
    name_tag = 'profileName'
    type_tag = 'profileType'
    parcels_tag = 'associatedProfileParcels'
    parcel_api_paths: ApiPathGroup = None

    post_model = FeatureProfileModel

    def __init__(self, data):
        super().__init__(data)

        # {<old parcel id>: <new parcel id>} map used to update parcel references with the new parcel ids
        self.id_mapping: Dict[str, str] = {}

    def associated_parcels(self, new_profile_id: str) -> Generator[Tuple[ApiPath, str, Dict[str, Any]], str, None]:
        def referenced_parcels_first(parcel_obj):
            return not self.parcel_api_paths.is_referenced_type(parcel_obj.parcelType)

        root_parcels = (ProfileParcelModel(**raw_parcel) for raw_parcel in self.data.get(self.parcels_tag, []))
        for root_parcel in sorted(root_parcels, key=referenced_parcels_first):
            # Traverse parcel tree under this root parcel
            yield from self.profile_parcel_coro(root_parcel, new_profile_id)

    def profile_parcel_coro(
            self, parcel: ProfileParcelModel, *element_ids: str,
            parent_parcel_type: Optional[str] = None) -> Generator[Tuple[ApiPath, str, Dict[str, Any]], str, None]:
        """
        Iterate over Config 2.0 feature profile parcels, starting with the provided parcel and recursively checking
        sub-parcels it may contain.
        @param parcel: parcel to be iterated over
        @param element_ids: Element IDs used to resolve path variables. First one is the feature profile ID. Parcels
                            with sub-parcels have their IDs included as well.
        @param parent_parcel_type: Parcel type of the parent, or None if this is a root parcel
        @yield: (<parcel api path>, <parcel info>, <parcel payload>) tuples
        @send: New element id, used to resolve the api path
        """
        api_path, is_reference = self.parcel_api_paths.api_path(PathKey(parcel.parcelType, parent_parcel_type))
        if api_path is None:
            raise ModelException(f"Parcel type {parcel.parcelType} is not supported")

        if is_reference:
            parcel_info = f'{parcel.payload.name} (parcel reference)'

            new_parcel_id = self.id_mapping.get(parcel.parcelId)
            if new_parcel_id is None:
                raise ModelException(f"{parcel_info}: Referenced parcel ID not found")

            parcel_payload = ProfileParcelReferenceModel(parcelId=new_parcel_id)
        else:
            parcel_info = parcel.payload.name
            parcel_payload = parcel.payload

        new_element_id = yield api_path.resolve(*element_ids), parcel_info, parcel_payload.dict(by_alias=True)

        self.id_mapping[parcel.parcelId] = new_element_id
        new_element_ids = element_ids + (new_element_id,)

        for sub_parcel in parcel.subparcels:
            yield from self.profile_parcel_coro(sub_parcel, *new_element_ids, parent_parcel_type=parcel.parcelType)


class FeatureProfileIndex(IndexConfigItem):
    iter_fields = IdName('profileId', 'profileName')


class AdminSettingsItem(ConfigItem):
    api_path = ApiPath('settings/configuration/{setting}')
    store_path = ('settings',)
    setting = None

    def __init__(self, data):
        """
        @param data: dict containing the information to be associated with this API item.
        """
        # Get requests return a dict as {'data': [{'domainIp': 'vbond.cisco.com', 'port': '12346'}]}
        super().__init__(data.get('data', [''])[0])

    @classmethod
    def get_raise(cls, api: Rest, *args, **kwargs):
        setting = kwargs.pop(cls.setting, None) or cls.setting

        return super().get_raise(api, *args, setting=setting, **kwargs)


class ServerInfo:
    root_dir = DATA_DIR
    store_file = 'server_info.json'

    def __init__(self, **kwargs):
        """
        @param kwargs: key-value pairs of information about the vManage server
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

        @param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        @return: ServerInfo object, or None if file does not exist
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

        @param node_dir: String indicating directory under root_dir used for all files from a given vManage node.
        @return: True indicates data has been saved. False indicates no data to save (and no file has been created).
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
    @param lower: If True, apply str.lower() to result.
    @param name: name string to be converted
    @return: string containing the filename-save version of item_name
    """
    # Inspired by Django's slugify function
    cleaned = re.sub(r'[^\w\s-]', '_', name, flags=re.ASCII)
    return cleaned.lower() if lower else cleaned


def update_ids(id_mapping_dict: Mapping[str, str], item_data: Dict[str, Any]) -> Dict[str, Any]:
    def replace_id(match):
        matched_id = match.group(0)
        return id_mapping_dict.get(matched_id, matched_id)

    dict_json = re.sub(r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}', replace_id, json.dumps(item_data))

    return json.loads(dict_json)


class ExtendedTemplate:
    template_pattern = re.compile(r'{name(?:\s+(?P<regex>.*?))?}')

    def __init__(self, name_regex: str):
        self.src_template = name_regex
        self.label_value_map = None

    def __call__(self, name: str) -> str:
        """
        Raise ValueError when issues are encountered while processing the name_regex
        @param name: Current item name
        @return: New name from item name using the name_regex
        """

        def regex_replace(match_obj):
            regex = match_obj.group('regex')
            if regex is not None:
                try:
                    regex_p = re.compile(regex)
                except re.error:
                    raise ValueError('regular expression is invalid') from None
                if not regex_p.groups:
                    raise ValueError('regular expression must include at least one capturing group')

                value, regex_p_subs = regex_p.subn(''.join(f'\\{group + 1}' for group in range(regex_p.groups)), name)
                new_value = value if regex_p_subs else ''
            else:
                new_value = name

            label = 'name_{count}'.format(count=len(self.label_value_map))
            self.label_value_map[label] = new_value

            return f'{{{label}}}'

        self.label_value_map = {}
        template, name_p_subs = self.template_pattern.subn(regex_replace, self.src_template)
        if not name_p_subs:
            raise ValueError('name-regex must include {name} variable')

        try:
            result_name = template.format(**self.label_value_map)
        except (KeyError, IndexError):
            raise ValueError('invalid name-regex') from None

        return result_name


def default_getter(*fields: str, default: Any = None) -> Callable:
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
