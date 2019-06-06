#! /usr/bin/env python3
"""
Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

"""
import logging
import argparse
import os
import os.path
from itertools import starmap
import requests.exceptions
from lib.config_items import *
from lib.rest_api import Rest, LoginFailedException
from lib.catalog import catalog_size, catalog_tags, catalog_entries, CATALOG_TAG_ALL, ordered_tags


__author__     = "Marcelo Reis"
__copyright__  = "Copyright (c) 2019 by Cisco Systems, Inc. All rights reserved."
__version__    = "0.1"
__maintainer__ = "Marcelo Reis"
__email__      = "mareis@cisco.com"
__status__     = "Development"


class Config:
    VMANAGE_DEFAULT_PORT = '8443'
    REST_DEFAULT_TIMEOUT = 300


def main(cli_args):
    logger = logging.getLogger('main')

    base_url = 'https://{address}:{port}'.format(address=cli_args.address, port=cli_args.port)
    work_dir = 'node_{address}'.format(address=cli_args.address)

    try:
        with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
            # Dispatch to the appropriate task handler
            cli_args.task(api, work_dir, cli_args.task_args)

    except LoginFailedException as ex:
        logger.fatal(ex)


def task_backup(api, work_dir, task_args):
    logger = logging.getLogger('task_backup')

    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py backup', description='{header}\nBackup task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                             help='''One or more tags matching items to be backed up. 
                                     Multiple tags should be separated by space.
                                     Available tags: {tag_options}. Special tag '{all}' denotes backup of all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    backup_args = task_parser.parse_args(task_args)

    logger.info('Starting backup task')
    for _, title, index_cls, item_cls in catalog_entries(*backup_args.tags):
        try:
            # Process index class
            item_index = index_cls(api.get(index_cls.api_path.get)['data'])
            if item_index.save(work_dir):
                logger.info('Backup {title} index'.format(title=title))
        except requests.exceptions.HTTPError:
            logger.info('Skipped backup {title}, item not supported by this vManage'.format(title=title))
            continue

        for item_id, item_name in item_index:
            try:
                # Process item class
                item_obj = item_cls(api.get(item_cls.api_path.get, item_id))
                if item_obj.is_readonly:
                    # Skip backing up factory default and readonly items
                    continue
                if item_obj.save(work_dir, template_name=item_name):
                    logger.info('Backup {title} {name}'.format(title=title, name=item_name))

                # Special case for DeviceTemplateAttached/DeviceTemplateValues
                if isinstance(item_obj, DeviceTemplate):
                    t_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id)['data'])
                    if t_attached.save(work_dir, template_name=item_name):
                        logger.info('Backup {title} {name} attached devices'.format(title=title, name=item_name))

                    uuids = list(t_attached)
                    template_values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(item_id, uuids),
                                                                    DeviceTemplateValues.api_path.post))
                    if template_values.save(work_dir, template_name=item_name):
                        logger.info('Backup {title} {name} values'.format(title=title, name=item_name))
            except requests.exceptions.HTTPError as ex:
                logger.error('Failed backup {title} {name}: {err}'.format(title=title, name=item_name, err=ex))

    logger.info('Backup task complete')


# TODO: Restore device attachments and values
def task_restore(api, work_dir, task_args):
    logger = logging.getLogger('task_restore')

    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py restore', description='{header}\nRestore task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                             help='''Tag matching items to be restored. 
                                     Items that are dependencies of the specified tag are automatically included.
                                     Available tags: {tag_options}. Special tag '{all}' denotes restore all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    restore_args = task_parser.parse_args(task_args)

    logger.info('Starting restore task')

    # id_mapping is {<old_id>: <new_id>}
    id_mapping = dict()

    for tag in ordered_tags(restore_args.tag):
        logger.info('Inspecting {tag} items'.format(tag=tag))

        for index_cls, title, item_dict in iter_saved_items(work_dir, tag):
            # Find existing names in target vManage
            try:
                existing_names = {item_name for item_id, item_name in index_cls(api.get(index_cls.api_path.get)['data'])}
            except requests.exceptions.HTTPError:
                logger.warning('Skipped restoring {title}, item not supported by this vManage'.format(title=title))
                continue
            # Restore items in item_dict
            for item_id, item_obj in item_dict.items():
                if item_obj.name in existing_names:
                    logger.info('Skipped {title} {name}, item with same name already on vManage'.format(
                        title=title, name=item_obj.name))
                    continue

                try:
                    reply_data = api.post(item_obj.post_data(id_mapping), item_obj.api_path.post)
                    if reply_data is not None:
                        id_mapping[item_id] = reply_data[item_obj.id_tag]
                    logger.info('Restored {title} {name}'.format(title=title, name=item_obj.name))
                except requests.exceptions.HTTPError as ex:
                    logger.error('Failed restoring {title} {name}: {err}'.format(title=title, name=item_obj.name, err=ex))

    logger.info('Restore task complete')


def iter_saved_items(work_dir, tag):
    """
    Return an iterator of config items loaded from work_dir, matching tag
    :param tag: Tag used to match which catalog entries to retrieve
    :param work_dir: Directory containing the backup files from a vManage node
    :return: Iterator of (<index_cls>, <catalog title>, <loaded_items_dict>)
    """
    def index_list_exist(index_list_entry):
        return index_list_entry[0] is not None

    def saved_items_entry(index_list, catalog_entry):
        items = ((item_id, catalog_entry.item_cls.load(work_dir, template_name=item_name))
                 for item_id, item_name in index_list)
        loaded_items = {item_id: item_obj
                        for item_id, item_obj in items if item_obj is not None}
        return catalog_entry.index_cls, catalog_entry.title, loaded_items

    index_list_entries = ((entry.index_cls.load(work_dir), entry) for entry in catalog_entries(tag))

    return starmap(saved_items_entry, filter(index_list_exist, index_list_entries))


# TODO: add pattern to match name of items to delete
def task_delete(api, work_dir, task_args):
    logger = logging.getLogger('task_delete')

    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py delete', description='{header}\nDelete task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                             help='''Tag matching items to be restored. 
                                     Items that are dependencies of the specified tag are automatically included.
                                     Available tags: {tag_options}. Special tag '{all}' denotes restore all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    restore_args = task_parser.parse_args(task_args)

    logger.info('Starting delete task')

    for _, title, index_cls, item_cls in catalog_entries(restore_args.tag):
        try:
            # Process index class
            item_index = index_cls(api.get(index_cls.api_path.get)['data'])
        except requests.exceptions.HTTPError:
            logger.info('Delete {title} skipped, item not supported by this vManage'.format(title=title))
            continue

        for item_id, item_name in item_index:
            if not item_name.startswith('ccc'):
                continue

            if api.delete(item_cls.api_path.delete, item_id):
                logger.info('Deleted {title} {name}'.format(title=title, name=item_name))
            else:
                logger.warning('Failed delete {title} {name}'.format(title=title, name=item_name))

    logger.info('Delete task complete')


# TODO: Create decorator to register tasks and provide task parser and logger
class TaskOptions:
    task_options = {
        'backup': task_backup,
        'restore': task_restore,
        'delete': task_delete,
    }

    @classmethod
    def task(cls, task_string):
        if task_string not in cls.task_options:
            raise argparse.ArgumentTypeError(
                'Invalid task. Options are: {options}'.format(options=cls.options()))

        return cls.task_options.get(task_string)

    @classmethod
    def options(cls):
        return ', '.join(cls.task_options)


class TagOptions:
    tag_options = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_string):
        if tag_string not in cls.tag_options:
            raise argparse.ArgumentTypeError('"{}" is not a valid tag. Available tags: {}.'.format(tag_string, cls.options()))

        return tag_string

    @classmethod
    def options(cls):
        return ', '.join([CATALOG_TAG_ALL] + sorted(catalog_tags()))


class EnvVar(argparse.Action):
    def __init__(self, envvar=None, required=True, default=None, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")

        default = default or os.environ.get(envvar)
        required = not required or default is None
        super().__init__(default=default, required=required, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)


if __name__ == '__main__':
    cli_parser = argparse.ArgumentParser(description=__doc__)
    cli_parser.add_argument('-a', '--address', metavar='<vmanage-ip>', action=EnvVar, envvar='VMANAGE_IP',
                            help='vManage IP address, can also be provided via VMANAGE_IP environment variable')
    cli_parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, envvar='VMANAGE_USER',
                            help='username, can also be provided via VMANAGE_USER environment variable')
    cli_parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, envvar='VMANAGE_PASSWORD',
                            help='password, can also be provided via VMANAGE_PASSWORD environment variable')
    cli_parser.add_argument('--port', metavar='<port>', nargs='?',
                            default=Config.VMANAGE_DEFAULT_PORT, const=Config.VMANAGE_DEFAULT_PORT,
                            help='vManage TCP port number (default is {port})'.format(port=Config.VMANAGE_DEFAULT_PORT))
    cli_parser.add_argument('--timeout', metavar='<timeout>', nargs='?', type=int,
                            default=Config.REST_DEFAULT_TIMEOUT, const=Config.REST_DEFAULT_TIMEOUT,
                            help='REST API timeout (default is {timeout}s)'.format(timeout=Config.REST_DEFAULT_TIMEOUT))
    cli_parser.add_argument('--verbose', action='store_true',
                            help='increase output verbosity')
    cli_parser.add_argument('--version', action='version',
                            version='''Sastre Version {version}. Catalog info: {num} items, tags: {tags}.
                                    '''.format(version=__version__, num=catalog_size(), tags=TagOptions.options()))
    cli_parser.add_argument('task', metavar='<task>', type=TaskOptions.task,
                            help='task to be performed ({options})'.format(options=TaskOptions.options()))
    cli_parser.add_argument('task_args', metavar='<arguments>', nargs=argparse.REMAINDER,
                            help='task parameters, if any')
    args = cli_parser.parse_args()

    # Logging setup
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO if args.verbose else logging.WARN)

    # Entry point
    main(args)
