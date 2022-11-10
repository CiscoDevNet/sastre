"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.tasks.utils
 This module implements task utility classes and functions
"""
import os
import re
import argparse
from datetime import date
from getpass import getpass
from typing import Callable
from cisco_sdwan.base.catalog import catalog_tags, op_catalog_tags, op_catalog_commands, CATALOG_TAG_ALL, OpType
from cisco_sdwan.tasks.common import Task
from cisco_sdwan.tasks.validators import (validate_workdir, validate_regex, validate_existing_file, validate_zip_file,
                                          validate_ipv4, validate_site_id, validate_ext_template, validate_version,
                                          validate_filename)

# Default local data store
DEFAULT_WORKDIR_FORMAT = 'backup_{address}_{date:%Y%m%d}'


def default_workdir(address):
    return DEFAULT_WORKDIR_FORMAT.format(date=date.today(), address=address or 'VMANAGE-ADDRESS')


class TaskOptions:
    _task_options = {}

    @classmethod
    def task(cls, task_str):
        task_cls = cls._task_options.get(task_str)
        if task_cls is None:
            raise argparse.ArgumentTypeError(f'Invalid task. Options are: {cls.options()}.')
        return task_cls

    @classmethod
    def options(cls):
        return ', '.join(cls._task_options)

    @classmethod
    def register(cls, task_name):
        """
        Decorator used for registering tasks.
        The class being decorated needs to be a subclass of Task.
        @param task_name: String presented to the user in order to select a task
        @return: decorator
        """

        def decorator(task_cls):
            if not isinstance(task_cls, type) or not issubclass(task_cls, Task):
                raise SastreException(f'Invalid task registration attempt: {task_cls.__name__}')

            cls._task_options[task_name] = task_cls
            return task_cls

        return decorator


class TagOptions:
    tag_options = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_str):
        if tag_str not in cls.tag_options:
            raise argparse.ArgumentTypeError(f'"{tag_str}" is not a valid tag. Available tags: {cls.options()}.')

        return tag_str

    @classmethod
    def tag_list(cls, tag_str_list):
        return [cls.tag(tag_str) for tag_str in tag_str_list]

    @classmethod
    def options(cls):
        return ', '.join(sorted(cls.tag_options, key=lambda x: '' if x == CATALOG_TAG_ALL else x))


class OpCmdOptions:
    @classmethod
    def tags(cls, op_type: OpType) -> str:
        return ', '.join(
            sorted(op_catalog_tags(op_type) | {CATALOG_TAG_ALL}, key=lambda x: '' if x == CATALOG_TAG_ALL else x)
        )

    @classmethod
    def commands(cls, op_type: OpType) -> str:
        return ', '.join(sorted(op_catalog_commands(op_type)))


class OpCmdSemantics(argparse.Action):
    # Using an action as opposed to a type check so that it can evaluate the full command line passed as opposed to
    # individual tokens.
    op_type: OpType = None

    def __call__(self, parser, namespace, values, option_string=None):
        full_command = ' '.join(values)
        pass_options = [
            len(values) == 1 and CATALOG_TAG_ALL in values,
            len(values) == 1 and set(values) <= op_catalog_tags(self.op_type),
            full_command in op_catalog_commands(self.op_type)
        ]
        if not any(pass_options):
            raise argparse.ArgumentError(self, f'"{full_command}" is not valid. '
                                               f'Group options: {OpCmdOptions.tags(self.op_type)}. '
                                               f'Command options: {OpCmdOptions.commands(self.op_type)}.')

        setattr(namespace, self.dest, values)


class RTCmdSemantics(OpCmdSemantics):
    op_type: OpType = OpType.RT


class StateCmdSemantics(OpCmdSemantics):
    op_type: OpType = OpType.STATE


class StatsCmdSemantics(OpCmdSemantics):
    op_type: OpType = OpType.STATS


#
# Validator wrappers to adapt pydantic validators to argparse
#

def regex_type(regex: str) -> str:
    try:
        validate_regex(regex)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return regex


def existing_workdir_type(workdir: str, *, skip_validation: bool = False) -> str:
    if not skip_validation:
        try:
            validate_workdir(workdir)
        except ValueError as ex:
            raise argparse.ArgumentTypeError(ex) from None

    return workdir


def filename_type(filename: str) -> str:
    try:
        validate_filename(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def existing_file_type(filename: str) -> str:
    try:
        validate_existing_file(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def zip_file_type(filename: str) -> str:
    try:
        validate_zip_file(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def ipv4_type(ipv4: str) -> str:
    try:
        validate_ipv4(ipv4)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return ipv4


def site_id_type(site_id: str) -> str:
    try:
        validate_site_id(site_id)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return site_id


def ext_template_type(template_str: str) -> str:
    try:
        validate_ext_template(template_str)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return template_str


def version_type(version_str: str) -> str:
    try:
        cleaned_version = validate_version(version_str)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return cleaned_version


#
# Argparse specific validators
#

def uuid_type(uuid_str: str) -> str:
    if re.match(r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$', uuid_str) is None:
        raise argparse.ArgumentTypeError(f'"{uuid_str}" is not a valid item ID.')

    return uuid_str


def non_empty_type(src_str: str) -> str:
    out_str = src_str.strip()
    if len(out_str) == 0:
        raise argparse.ArgumentTypeError('Value cannot be empty.')

    return out_str


def int_type(min_val: int, max_val: int, value_str: str) -> int:
    try:
        value_int = int(value_str)
        if not min_val <= value_int <= max_val:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError(f'Invalid value: "{value_str}". Must be an integer between '
                                         f'{min_val} and {max_val}, inclusive.') from None

    return value_int


#
# Miscellaneous cli-input / argparse
#

class TrackedValidator:
    def __init__(self, validator_fn: Callable):
        self.num_calls = 0
        self.validator_fn = validator_fn

    @property
    def called(self) -> bool:
        return self.num_calls > 0

    def __call__(self, *validator_fn_args):
        self.num_calls += 1

        return self.validator_fn(*validator_fn_args)


class ConditionalValidator:
    def __init__(self, validator_fn: Callable, tracked_validator_obj: TrackedValidator):
        self.validator_fn = validator_fn
        self.tracked_validator_obj = tracked_validator_obj

    def __call__(self, *validator_fn_args):
        return self.validator_fn(*validator_fn_args, skip_validation=self.tracked_validator_obj.called)


class EnvVar(argparse.Action):
    def __init__(self, nargs=None, envvar=None, required=True, default=None, **kwargs):
        if nargs is not None:
            raise ValueError('nargs not allowed')
        if envvar is None:
            raise ValueError('envvar is required')

        default = os.environ.get(envvar) or default
        required = required and default is None
        super().__init__(default=default, required=required, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)


class PromptArg:
    def __init__(self, argument, prompt, secure_prompt=False, validate=non_empty_type):
        self.argument = argument
        self.prompt = prompt
        self.prompt_func = getpass if secure_prompt else input
        self.validate = validate

    def __call__(self):
        while True:
            try:
                value = self.validate(self.prompt_func(self.prompt))
            except argparse.ArgumentTypeError as ex:
                print(f'{ex} Please try again, or ^C to terminate.')
            else:
                return value


#
# Exceptions
#

class SastreException(Exception):
    """ Exception for main app errors """
    pass
