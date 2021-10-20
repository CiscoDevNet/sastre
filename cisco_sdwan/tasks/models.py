import json
import re
from pathlib import Path
from typing import Optional, List, Callable, Any
from pydantic import BaseModel, validator, Field, Extra
from cisco_sdwan.base.catalog import OpType, CATALOG_TAG_ALL, op_catalog_tags, op_catalog_commands, catalog_tags
from cisco_sdwan.base.models_base import filename_safe, DATA_DIR, ExtendedTemplate
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


def validate_ext_template(template_str: str) -> str:
    # ExtendedTemplate will raise ValueError on validation failures
    ExtendedTemplate(template_str)('test')

    return template_str


def validate_version(version_str: str) -> str:
    # Development versions may follow this format: '20.1.999-98'
    if re.match(r'\d+([.-]\d+){1,3}$', version_str) is None:
        raise ValueError(f'"{version_str}" is not a valid version identifier.')

    return '.'.join(([str(int(v)) for v in version_str.replace('-', '.').split('.')] + ['0', ])[:2])


def const(default_value: Any) -> Field:
    """
    Defines a model field as constant. That is, it cannot be set to any value other than the default value
    """
    return Field(default_value, const=True)


# Models
class TaskArgs(BaseModel, extra=Extra.forbid):
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
