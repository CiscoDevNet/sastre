"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.utils
 This module implements task utility classes and functions
"""
import os
import re
import argparse
from pathlib import Path
from cisco_sdwan.base.catalog import catalog_tags, CATALOG_TAG_ALL
from cisco_sdwan.base.models_base import filename_safe, DATA_DIR
from .common import Task


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


class ShowOptions:
    _show_options = {}

    @classmethod
    def option(cls, option_str):
        option_fn = cls._show_options.get(option_str)
        if option_fn is None:
            raise argparse.ArgumentTypeError('Invalid show option. Options are: {ops}.'.format(ops=cls.options()))
        return option_fn

    @classmethod
    def options(cls):
        return ', '.join(cls._show_options)

    @classmethod
    def register(cls, option_str):
        """
        Decorator used for registering show task options.
        :param option_str: String presented to the user in order to select a show option
        :return: decorator
        """
        def decorator(option_fn):
            cls._show_options[option_str] = option_fn
            return option_fn

        return decorator


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


class EnvVar(argparse.Action):
    def __init__(self, envvar=None, required=True, default=None, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")

        default = default or os.environ.get(envvar)
        required = not required or default is None
        super().__init__(default=default, required=required, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)


class SastreException(Exception):
    """ Exception for main app errors """
    pass
