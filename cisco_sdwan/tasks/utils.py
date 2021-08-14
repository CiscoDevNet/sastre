"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.utils
 This module implements task utility classes and functions
"""
import os
import re
import argparse
from datetime import date
from getpass import getpass
from pathlib import Path
from cisco_sdwan.base.catalog import catalog_tags, op_catalog_tags, op_catalog_commands, CATALOG_TAG_ALL, OpType
from cisco_sdwan.base.models_base import filename_safe, DATA_DIR, ExtendedTemplate
from .common import Task

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
        :param task_name: String presented to the user in order to select a task
        :return: decorator
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


def regex_type(regex_str):
    try:
        re.compile(regex_str)
    except (re.error, TypeError):
        if regex_str is not None:
            raise argparse.ArgumentTypeError(f'"{regex_str}" is not a valid regular expression.') from None

    return regex_str


def existing_workdir_type(workdir_str):
    if not Path(DATA_DIR, workdir_str).exists():
        raise argparse.ArgumentTypeError(f'Work directory "{workdir_str}" not found.')

    return workdir_str


def existing_file_type(filename_str):
    if not Path(filename_str).exists():
        raise argparse.ArgumentTypeError(f'File "{filename_str}" not found.')

    return filename_str


def filename_type(name_str):
    # Also allow . on filename, on top of what's allowed by filename_safe
    if re.sub(r'\.', '_', name_str) != filename_safe(name_str):
        raise argparse.ArgumentTypeError(
            f'Invalid name "{name_str}". Only alphanumeric characters, "-", "_", and "." are allowed.'
        )
    return name_str


def uuid_type(uuid_str):
    if re.match(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', uuid_str) is None:
        raise argparse.ArgumentTypeError(f'"{uuid_str}" is not a valid item ID.')

    return uuid_str


def non_empty_type(src_str):
    out_str = src_str.strip()
    if len(out_str) == 0:
        raise argparse.ArgumentTypeError('Value cannot be empty.')

    return out_str


def ipv4_type(ipv4_str):
    if re.match(r'\d+(?:\.\d+){3}$', ipv4_str) is None:
        raise argparse.ArgumentTypeError(f'"{ipv4_str}" is not a valid IPv4 address.')

    return ipv4_str


def site_id_type(site_id_str):
    try:
        site_id = int(site_id_str)
        if not 0 <= site_id <= 4294967295:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError(f'"{site_id_str}" is not a valid site-id.') from None

    return site_id_str


def version_type(version_str):
    # Development versions may follow this format: '20.1.999-98'
    if re.match(r'\d+([.-]\d+){1,3}$', version_str) is None:
        raise argparse.ArgumentTypeError(f'"{version_str}" is not a valid version identifier.')

    return '.'.join(([str(int(v)) for v in version_str.replace('-', '.').split('.')] + ['0', ])[:2])


def int_type(min_val, max_val, value_str):
    try:
        value_int = int(value_str)
        if not min_val <= value_int <= max_val:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError(f'Invalid value: "{value_str}". Must be an integer between '
                                         f'{min_val} and {max_val}, inclusive.') from None

    return value_int


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


def ext_template_type(template_str):
    try:
        ExtendedTemplate(template_str)('test')
    except re.error:
        raise argparse.ArgumentTypeError('regular expression is invalid') from None
    except (KeyError, ValueError) as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return template_str


class SastreException(Exception):
    """ Exception for main app errors """
    pass
