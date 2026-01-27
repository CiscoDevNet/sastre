from typing import Optional, Any, Annotated
from pydantic import BaseModel, field_validator, Field, AfterValidator, ConfigDict, ValidationInfo
from cisco_sdwan.base.catalog import OpType, CATALOG_TAG_ALL, op_catalog_tags, op_catalog_commands, catalog_tags
from cisco_sdwan.tasks.utils import OpCmdOptions
from cisco_sdwan.tasks.validators import validate_regex, validate_filename, validate_workdir


# Model field validators
def validate_op_cmd(op_type: OpType, cmd_list: list[str]) -> list[str]:
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


CatalogTag = Annotated[str, AfterValidator(validate_catalog_tag)]


def validate_workdir_conditional(workdir: str, info: ValidationInfo) -> str:
    """
    Validate workdir only if archive was not set (i.e. is None).
    In the model, the archive attribute needs to be defined before workdir.
    """
    if not info.data.get('archive'):
        validate_workdir(workdir)

    return workdir


def const(field_type: type[Any], default_value: Any) -> Annotated[type[Any], ...]:
    """
    Defines a model field as constant. That is, it cannot be set to any value other than the default value.
    """
    # noinspection PyUnusedLocal
    def validate(value):
        raise ValueError('This is a constant field and cannot be explicitly set or modified')

    return Annotated[field_type, Field(default_value, frozen=True), AfterValidator(validate)]


# Models
IPv4AddressStr = Annotated[str, Field(pattern=r'\d+(?:\.\d+){3}$')]


class TaskArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', use_enum_values=True)


class TableTaskArgs(TaskArgs):
    exclude: Optional[str] = None
    include: Optional[str] = None
    save_csv: Optional[str] = None
    save_json: Optional[str] = None

    # Validators
    _validate_regex = field_validator('exclude', 'include')(validate_regex)
    _validate_filename = field_validator('save_csv', 'save_json')(validate_filename)
