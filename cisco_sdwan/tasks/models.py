from typing import Optional, List, Any, Dict
from pydantic import BaseModel, validator, Field, Extra
from cisco_sdwan.base.catalog import OpType, CATALOG_TAG_ALL, op_catalog_tags, op_catalog_commands, catalog_tags
from cisco_sdwan.tasks.utils import OpCmdOptions
from cisco_sdwan.tasks.validators import validate_regex, validate_filename, validate_workdir


# Model field validators
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


catalog_tag_options = catalog_tags() | {CATALOG_TAG_ALL}


def validate_catalog_tag(tag: str) -> str:
    if tag not in catalog_tag_options:
        options = ', '.join(sorted(catalog_tag_options, key=lambda x: '' if x == CATALOG_TAG_ALL else x))
        raise ValueError(f'"{tag}" is not a valid tag. Available tags: {options}.')

    return tag


def validate_workdir_conditional(workdir: str, values: Dict[str, Any]) -> str:
    """
    Validate workdir only if archive was not set (i.e. is None).
    In the model, the archive attribute needs to be defined before workdir.
    """
    if not values.get('archive'):
        validate_workdir(workdir)

    return workdir


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


class TableTaskArgs(TaskArgs):
    exclude: Optional[str] = None
    include: Optional[str] = None
    save_csv: Optional[str] = None
    save_json: Optional[str] = None

    # Validators
    _validate_regex = validator('exclude', 'include', allow_reuse=True)(validate_regex)
    _validate_filename = validator('save_csv', 'save_json', allow_reuse=True)(validate_filename)
