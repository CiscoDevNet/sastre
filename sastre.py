#! /usr/bin/env python
"""
Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

"""
import logging
import argparse
import os
import os.path
import requests.exceptions
from lib.config_items import *
from lib.rest_api import Rest, LoginFailedException
from lib.catalog import catalog_size, catalog_tags, catalog_items, CATALOG_TAG_ALL


__author__     = "Marcelo Reis"
__copyright__  = "Copyright (c) 2019 by Cisco Systems, Inc. All rights reserved."
__version__    = "0.1"
__maintainer__ = "Marcelo Reis"
__email__      = "mareis@cisco.com"
__status__     = "Development"


class Config:
    VMANAGE_DEFAULT_PORT = '8443'


def main(cli_args):
    base_url = 'https://{address}:{port}'.format(address=cli_args.address, port=cli_args.port)
    work_dir = 'node_{address}'.format(address=cli_args.address)

    # Dispatch to the appropriate task handler
    cli_args.task(base_url, work_dir, cli_args.user, cli_args.password, cli_args.task_args)


def task_backup(base_url, work_dir, user, password, task_args):
    logger = logging.getLogger('task_backup')

    # Parse task_args
    backup_parser = argparse.ArgumentParser(prog='sastre.py backup', description='{header}\nBackup task:'.format(header=__doc__),
                                            formatter_class=argparse.RawDescriptionHelpFormatter)
    backup_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                               help='''One or more tags matching items to be backed up. 
                                       Multiple tags should be separated by space.
                                       Available tags: {tag_options}. Special tag '{all}' denotes backup of all items.
                                    '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    backup_args = backup_parser.parse_args(task_args)

    logger.info('Starting backup task')
    with Rest(base_url, user, password) as api:

        for _, title, index_cls, handler_cls in catalog_items(*backup_args.tags):
            try:
                # Process index class
                cfg_item_index = index_cls(api.get(index_cls.api_path.get)['data'])
                if cfg_item_index.save(work_dir):
                    logger.info('Backup {title} list'.format(title=title))

            except requests.exceptions.HTTPError:
                logger.info('Backup {title} skipped, item not supported by this vManage'.format(title=title))

            else:
                for cfg_item_id, cfg_item_name in cfg_item_index:
                    # Process config item class
                    cfg_item = handler_cls(api.get(handler_cls.api_path.get, cfg_item_id))
                    if cfg_item.save(work_dir, template_name=cfg_item_name):
                        logger.info('Backup {title} {name}'.format(title=title, name=cfg_item_name))

                    # Special case for DeviceTemplateAttached/DeviceTemplateValues
                    if isinstance(cfg_item, DeviceTemplate):
                        t_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, cfg_item_id)['data'])
                        if t_attached.save(work_dir, template_name=cfg_item_name):
                            logger.info('Backup {title} {name} attached devices'.format(title=title, name=cfg_item_name))

                        uuids = list(t_attached)
                        template_values = DeviceTemplateValues(api.post(DeviceTemplateValues.api_params(cfg_item_id, uuids),
                                                                        DeviceTemplateValues.api_path.post))
                        if template_values.save(work_dir, template_name=cfg_item_name):
                            logger.info('Backup {title} {name} values'.format(title=title, name=cfg_item_name))

    logger.info('Backup task complete')


def task_restore(base_url, work_dir, user, password, task_args):
    logger = logging.getLogger('task_restore')

    # Parse task_args
    restore_parser = argparse.ArgumentParser(prog='sastre.py restore', description='{header}\nRestore task:'.format(header=__doc__),
                                             formatter_class=argparse.RawDescriptionHelpFormatter)
    restore_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                help='''One or more tags matching items to be restored. 
                                        Multiple tags should be separated by space.
                                        Available tags: {tag_options}. Special tag '{all}' denotes backup of all items.
                                     '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    restore_args = restore_parser.parse_args(task_args)
    logger.info('Starting restore task')

    item_tracker_dict = load_cfg_items(work_dir)

    with Rest(base_url, user, password) as api:
        # 1. Restore items with no dependencies
        item_restore_list = [item_tracker for item_tracker in item_tracker_dict.values() if not item_tracker.has_dependencies]
        for item in item_restore_list:
            r = api.post(item.cfg_item.post_data, item.cfg_item.api_path.post)
            print(r)
            break

    for i in item_restore_list:
        print('Name: {}, backpointers: {}, dependencies: {}'.format(i.cfg_item.get_name(), i._backpointers, i._dependency_set))


    # 2. Update new IDs on all items listed in backpointers, delete dependency on those items.

    # 3. Go back to 1. until all items have been uploaded


    logger.info('Restore task complete')


class ItemTracker:
    def __init__(self, cfg_item):
        self.cfg_item = cfg_item
        self.restored = False

        self._backpointers = set()
        self._dependency_set = cfg_item.get_dependencies()

    @property
    def has_dependencies(self):
        return len(self._dependency_set) > 0

    def del_dependency(self, item_id):
        self._dependency_set.discard(item_id)

    def dependency_iter(self):
        return iter(self._dependency_set)

    def add_backpointer(self, item_id):
        self._backpointers.add(item_id)

    def get_refcount(self):
        return len(self._backpointers)


def load_cfg_items(work_dir):
    """
    Load all config items from specified work_dir
    :param work_dir: directory with all files from a vManage node
    :return:
    """
    def item_list_exist(index_handler_tuple):
        """
        :param index_handler_tuple: (<index_cls instance>, <handler_cls>)
        :return: True if index_cls instance was loaded (i.e. not None), False if index file didn't exist
        """
        return index_handler_tuple[0] is not None

    item_list_load = [(item.index_cls.load(work_dir), item.handler_cls) for item in catalog_items(CATALOG_TAG_ALL)]

    item_tracker_dict = {item_id: ItemTracker(handler_cls.load(work_dir, template_name=item_name))
                         for index_list, handler_cls in filter(item_list_exist, item_list_load)
                         for item_id, item_name in index_list}

    # Update item backpointers from dependencies
    for item_id, item_tracker in item_tracker_dict.items():
        for dependency_id in item_tracker.dependency_iter():
            item_tracker_dict[dependency_id].add_backpointer(item_id)

    return item_tracker_dict


class TaskOptions:
    task_options = {
        'backup': task_backup,
        'restore': task_restore,
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-a', '--address', metavar='<vmanage-ip>', action=EnvVar, envvar='VMANAGE_IP',
                        help='vManage IP address, can also be provided via VMANAGE_IP environment variable')
    parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, envvar='VMANAGE_USER',
                        help='username, can also be provided via VMANAGE_USER environment variable')
    parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, envvar='VMANAGE_PASSWORD',
                        help='password, can also be provided via VMANAGE_PASSWORD environment variable')
    parser.add_argument('--port', metavar='<port>', nargs='?', default=Config.VMANAGE_DEFAULT_PORT, const=Config.VMANAGE_DEFAULT_PORT,
                        help='vManage TCP port number (default is {port})'.format(port=Config.VMANAGE_DEFAULT_PORT))
    parser.add_argument('--verbose', action='store_true',
                        help='increase output verbosity')
    parser.add_argument('--version', action='version',
                        version='''Sastre Version {version}. Catalog info: {num} items, tags: {tags}.
                                '''.format(version=__version__, num=catalog_size(), tags=TagOptions.options()))
    parser.add_argument('task', metavar='<task>', type=TaskOptions.task,
                        help='task to be performed ({options})'.format(options=TaskOptions.options()))
    parser.add_argument('task_args', metavar='<arguments>', nargs=argparse.REMAINDER,
                        help='task parameters, if any')
    args = parser.parse_args()

    # Logging setup
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO if args.verbose else logging.WARN)

    try:
        main(args)
    except LoginFailedException as e:
        logging.getLogger(__name__).fatal(e)
