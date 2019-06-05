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
from lib.catalog import catalog_size, catalog_tags, catalog_items, CATALOG_TAG_ALL, ordered_tags


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
    restore_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                help='''Tag matching items to be restored. 
                                        Items that are dependencies of the specified tag are automatically included.
                                        Available tags: {tag_options}. Special tag '{all}' denotes restore all items.
                                     '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    restore_args = restore_parser.parse_args(task_args)

    logger.info('Starting restore task')
    with Rest(base_url, user, password) as api:
        # id_mapping is {<old_id>: <new_id>}
        id_mapping = dict()

        for tag in ordered_tags(restore_args.tag):
            logger.info('Restoring {tag} items'.format(tag=tag))
            for cfg_item_id, cfg_item in load_cfg_items(work_dir, tag).items():
                reply_data = api.post(cfg_item.post_data(id_mapping, new_name='abc_{}'.format(cfg_item.name)), cfg_item.api_path.post)
                if reply_data is not None:
                    id_mapping[cfg_item_id] = reply_data[cfg_item.id_tag]

                logger.info('Restored {tag} {name}'.format(tag=tag, name=cfg_item.name))

    logger.info('Restore task complete')

# TODO: Restore verify if present before pushing, unless rename is provided


def load_cfg_items(work_dir, tag):
    """
    Load config items from work_dir matching tag
    :param tag: Tag used to match which catalog entries to retrieve
    :param work_dir: Directory containing the files from a vManage node
    :return: Dict of {<cfg item id>: <cfg item>} containing the items that matched the specified tag
    """
    def item_list_exist(index_handler_tuple):
        """
        :param index_handler_tuple: (<index_cls instance>, <handler_cls>)
        :return: True if index_cls instance was loaded (i.e. not None), False if index file didn't exist
        """
        return index_handler_tuple[0] is not None

    item_list_index = [(item.index_cls.load(work_dir), item.handler_cls) for item in catalog_items(tag)]

    return {item_id: item_cls.load(work_dir, template_name=item_name)
            for index_list, item_cls in filter(item_list_exist, item_list_index)
            for item_id, item_name in index_list}


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
