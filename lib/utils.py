"""
Utility classes and functions

"""
import os
import re
import argparse
from lib.catalog import catalog_tags, CATALOG_TAG_ALL, BASE_DATA_DIR


class Task:
    @staticmethod
    def parser(default_work_dir, task_args):
        raise NotImplementedError()

    @staticmethod
    def runner(api, parsed_args):
        raise NotImplementedError()


class TaskOptions:
    _task_options = {}

    @classmethod
    def task(cls, task_string):
        if task_string not in cls._task_options:
            raise argparse.ArgumentTypeError(
                'Invalid task. Options are: {options}'.format(options=cls.options())
            )
        return cls._task_options.get(task_string)

    @classmethod
    def options(cls):
        return ', '.join(cls._task_options)

    @classmethod
    def register(cls, task_name):
        """
        Decorator used for registering tasks.
        The class being decorated needs to be a subclass of Task.
        :param task_name:
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


def regex_type(regex_string):
    try:
        re.compile(regex_string)
    except re.error:
        raise argparse.ArgumentTypeError('"{regex}" is not a valid regular expression.'.format(regex=regex_string))

    return regex_string


def existing_workdir_type(workdir_string):
    if not os.path.exists(os.path.join(BASE_DATA_DIR, workdir_string)):
        raise argparse.ArgumentTypeError('Work directory "{directory}" not found.'.format(directory=workdir_string))

    return workdir_string


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
