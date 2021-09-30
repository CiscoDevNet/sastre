import json
import re
from pathlib import Path
from typing import Optional, List, Callable
from pydantic import BaseModel, validator, conint
from cisco_sdwan.base.catalog import OpType, CATALOG_TAG_ALL, op_catalog_tags, op_catalog_commands, catalog_tags
from cisco_sdwan.base.models_base import filename_safe, DATA_DIR
from cisco_sdwan.tasks.utils import OpCmdOptions


# Model field validators
def validate_regex(regex: str) -> str:
    try:
        re.compile(regex)
    except (re.error, TypeError):
        raise ValueError(f'"{regex}" is not a valid regular expression.') from None
    return regex


def validate_workdir(workdir: str) -> str:
    if not Path(DATA_DIR, workdir).exists():
        raise ValueError(f'Work directory "{workdir}" not found.')

    return workdir


def validate_filename(filename: str) -> str:
    """ Validate file name. If filename is a path containing a directory, validate whether it exists.
    """
    file_path = Path(filename)
    if not file_path.parent.exists():
        raise ValueError(f'Directory for "{filename}" does not exist')

    # Also allow . on filename, on top of what's allowed by filename_safe
    if re.sub(r'\.', '_', file_path.name) != filename_safe(file_path.name):
        raise ValueError(
            f'Invalid name "{file_path.name}". Only alphanumeric characters, "-", "_", and "." are allowed.'
        )
    return filename


def validate_existing_file(filename: str) -> str:
    if not Path(filename).exists():
        raise ValueError(f'File "{filename}" not found.')

    return filename


def validate_ipv4(ipv4_str: str) -> str:
    if re.match(r'\d+(?:\.\d+){3}$', ipv4_str) is None:
        raise ValueError(f'"{ipv4_str}" is not a valid IPv4 address.')

    return ipv4_str


def validate_site_id(site_id: str) -> int:
    try:
        site_id = int(site_id)
        if not 0 <= site_id <= 4294967295:
            raise ValueError()
    except ValueError:
        raise ValueError(f'"{site_id}" is not a valid site-id.') from None

    return site_id


def validate_op_cmd(op_type: OpType, cmd_list: List[str]) -> List[str]:
    full_command = ' '.join(cmd_list)
    pass_options = [
        len(cmd_list) == 1 and CATALOG_TAG_ALL in cmd_list,
        len(cmd_list) == 1 and set(cmd_list) <= op_catalog_tags(op_type),
        full_command in op_catalog_commands(op_type)
    ]
    if not any(pass_options):
        raise ValueError(f'"{full_command}" is not valid. '
                         f'Group options: {OpCmdOptions.tags(op_type)}. '
                         f'Command options: {OpCmdOptions.commands(op_type)}.')
    return cmd_list


def validate_json(json_str: str) -> str:
    try:
        json.loads(json_str)
    except json.JSONDecodeError as ex:
        raise ValueError(f'Invalid JSON data: {ex}') from None

    return json_str


catalog_tag_options = catalog_tags() | {CATALOG_TAG_ALL}


def validate_catalog_tag(tag: str) -> str:
    if tag not in catalog_tag_options:
        options = ', '.join(sorted(catalog_tag_options, key=lambda x: '' if x == CATALOG_TAG_ALL else x))
        raise ValueError(f'"{tag}" is not a valid tag. Available tags: {options}.')

    return tag


# Models
class TaskArgs(BaseModel):
    def __init__(self, **kwargs):
        # Dummy init used so PyCharm type checker can recognize TaskArgs parameters
        super().__init__(**kwargs)


class SubTaskArgs(TaskArgs):
    subtask_info: str
    subtask_handler: Callable

    regex: Optional[str] = None
    not_regex: Optional[str] = None
    save_csv: Optional[str] = None
    save_json: Optional[str] = None
    # Validators
    _validate_regex = validator('regex', 'not_regex', allow_reuse=True)(validate_regex)
    _validate_filename = validator('save_csv', 'save_json', allow_reuse=True)(validate_filename)


class ShowArgs(SubTaskArgs):
    reachable: bool = False
    site: Optional[int] = None
    system_ip: Optional[str] = None
    # Validators
    _validate_site_id = validator('site', allow_reuse=True)(validate_site_id)
    _validate_ipv4 = validator('system_ip', allow_reuse=True)(validate_ipv4)


class ShowRealtimeArgs(ShowArgs):
    cmd: List[str]
    detail: bool = False

    # Validators
    @validator('cmd')
    def validate_cmd(cls, cmd_list: List[str]) -> List[str]:
        return validate_op_cmd(OpType.RT, cmd_list)


class ShowStateArgs(ShowArgs):
    cmd: List[str]
    detail: bool = False

    # Validators
    @validator('cmd')
    def validate_cmd(cls, cmd_list: List[str]) -> List[str]:
        return validate_op_cmd(OpType.STATE, cmd_list)


class ShowStatisticsArgs(ShowArgs):
    cmd: List[str]
    detail: bool = False
    days: conint(ge=0, lt=10000) = 0
    hours: conint(ge=0, lt=10000) = 0

    # Validators
    @validator('cmd')
    def validate_cmd(cls, cmd_list: List[str]) -> List[str]:
        return validate_op_cmd(OpType.STATS, cmd_list)


class ListArgs(SubTaskArgs):
    workdir: Optional[str] = None
    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)


class ListConfigArgs(ListArgs):
    tags: List[str]
    # Validators
    _validate_tags = validator('tags', each_item=True, allow_reuse=True)(validate_catalog_tag)


class ShowTemplateArgs(SubTaskArgs):
    workdir: Optional[str] = None
    # Validators
    _validate_workdir = validator('workdir', allow_reuse=True)(validate_workdir)


class ShowTemplateRefArgs(ShowTemplateArgs):
    with_refs: bool = False
