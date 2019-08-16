"""
Utility classes and functions

"""
import os
import re
import argparse
from lib.task_common import Task
from lib.catalog import catalog_tags, CATALOG_TAG_ALL, BASE_DATA_DIR


class TaskOptions:
    _task_options = {}

    @classmethod
    def task(cls, task_string):
        task_cls = cls._task_options.get(task_string)
        if task_cls is None:
            raise argparse.ArgumentTypeError('Invalid task. Options are: {options}.'.format(options=cls.options()))
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
                raise SastreException('Invalid task registration attempt: {}'.format(task_cls.__name__))

            cls._task_options[task_name] = task_cls
            return task_cls

        return decorator


class TagOptions:
    tag_options = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_string):
        if tag_string not in cls.tag_options:
            raise argparse.ArgumentTypeError(
                '"{tag}" is not a valid tag. Available tags: {options}.'.format(tag=tag_string, options=cls.options())
            )
        return tag_string

    @classmethod
    def options(cls):
        return ', '.join([CATALOG_TAG_ALL] + sorted(catalog_tags()))


class ShowOptions:
    _show_options = {}

    @classmethod
    def option(cls, option_string):
        option_fn = cls._show_options.get(option_string)
        if option_fn is None:
            raise argparse.ArgumentTypeError('Invalid show option. Options are: {ops}.'.format(ops=cls.options()))
        return option_fn

    @classmethod
    def options(cls):
        return ', '.join(cls._show_options)

    @classmethod
    def register(cls, option_string):
        """
        Decorator used for registering show task options.
        :param option_string: String presented to the user in order to select a show option
        :return: decorator
        """
        def decorator(option_fn):
            cls._show_options[option_string] = option_fn
            return option_fn

        return decorator


def regex_type(regex_string):
    try:
        re.compile(regex_string)
    except re.error:
        raise argparse.ArgumentTypeError('"{regex}" is not a valid regular expression.'.format(regex=regex_string))

    return regex_string


def directory_type(workdir_string):
    if not os.path.exists(os.path.join(BASE_DATA_DIR, workdir_string)):
        raise argparse.ArgumentTypeError('Work directory "{directory}" not found.'.format(directory=workdir_string))

    return workdir_string


def uuid_type(uuid_string):
    if re.match(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', uuid_string) is None:
        raise argparse.ArgumentTypeError('"{uuid}" is not a valid item ID.'.format(uuid=uuid_string))

    return uuid_string


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
