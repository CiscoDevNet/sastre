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
from cisco_sdwan.base.catalog import catalog_tags, CATALOG_TAG_ALL
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
            raise argparse.ArgumentTypeError('Invalid task. Options are: {ops}.'.format(ops=cls.options()))
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
                raise SastreException('Invalid task registration attempt: {name}'.format(name=task_cls.__name__))

            cls._task_options[task_name] = task_cls
            return task_cls

        return decorator


class TagOptions:
    tag_options = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_str):
        if tag_str not in cls.tag_options:
            raise argparse.ArgumentTypeError(
                '"{tag}" is not a valid tag. Available tags: {ops}.'.format(tag=tag_str, ops=cls.options())
            )
        return tag_str

    @classmethod
    def options(cls):
        return ', '.join([CATALOG_TAG_ALL] + sorted(catalog_tags()))


def regex_type(regex_str):
    try:
        re.compile(regex_str)
    except re.error:
        raise argparse.ArgumentTypeError('"{regex}" is not a valid regular expression.'.format(regex=regex_str))

    return regex_str


def existing_file_type(workdir_str):
    if not Path(DATA_DIR, workdir_str).exists():
        raise argparse.ArgumentTypeError('Work directory "{directory}" not found.'.format(directory=workdir_str))

    return workdir_str


def filename_type(name_str):
    # Also allow . on filename, on top of what's allowed by filename_safe
    if re.sub(r'\.', '_', name_str) != filename_safe(name_str):
        raise argparse.ArgumentTypeError(
            'Invalid name "{name}". Only alphanumeric characters, "-", "_", and "." are allowed.'.format(name=name_str)
        )
    return name_str


def uuid_type(uuid_str):
    if re.match(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', uuid_str) is None:
        raise argparse.ArgumentTypeError('"{uuid}" is not a valid item ID.'.format(uuid=uuid_str))

    return uuid_str


def non_empty_type(src_str):
    out_str = src_str.strip()
    if len(out_str) == 0:
        raise argparse.ArgumentTypeError('Value cannot be empty.')

    return out_str


def version_type(version_str):
    # Development versions may follow this format: '20.1.999-98'
    if re.match(r'(\d+[.-])*\d+$', version_str) is None:
        raise argparse.ArgumentTypeError(f'"{version_str}" is not a valid version identifier.')

    return '.'.join(([str(int(v)) for v in version_str.replace('-', '.').split('.')] + ['0', ])[:2])


class EnvVar(argparse.Action):
    def __init__(self, nargs=None, envvar=None, required=True, default=None, **kwargs):
        if nargs is not None:
            raise ValueError('nargs not allowed')
        if envvar is None:
            raise ValueError('envvar is required')

        default = default or os.environ.get(envvar)
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
                print('{msg} Please try again, or ^C to terminate.'.format(msg=ex))
            else:
                return value


def ext_template_type(template_str):
    try:
        ExtendedTemplate(template_str)('test')
    except re.error:
        raise argparse.ArgumentTypeError('regular expression is invalid')
    except (KeyError, ValueError) as ex:
        raise argparse.ArgumentTypeError(ex)

    return template_str


class SastreException(Exception):
    """ Exception for main app errors """
    pass
