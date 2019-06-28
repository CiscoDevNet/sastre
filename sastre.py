#! /usr/bin/env python3
"""
Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

"""
import logging
import argparse
import os
import os.path
import re
import time
from itertools import starmap
import requests.exceptions
from lib.config_items import *
from lib.rest_api import Rest, LoginFailedException
from lib.catalog import catalog_size, catalog_tags, catalog_entries, CATALOG_TAG_ALL, sequenced_tags

__author__     = "Marcelo Reis"
__copyright__  = "Copyright (c) 2019 by Cisco Systems, Inc. All rights reserved."
__version__    = "0.4"
__maintainer__ = "Marcelo Reis"
__email__      = "mareis@cisco.com"
__status__     = "Development"


class Config:
    VMANAGE_DEFAULT_PORT = '8443'
    REST_DEFAULT_TIMEOUT = 300
    ACTION_INTERVAL = 5
    ACTION_TIMEOUT = 300


# TODO: Batch add users
def main(cli_args):
    logger = logging.getLogger('main')

    base_url = 'https://{address}:{port}'.format(address=cli_args.address, port=cli_args.port)
    default_work_dir = 'node_{address}'.format(address=cli_args.address)

    try:
        with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
            # Dispatch to the appropriate task handler
            cli_args.task(api, default_work_dir, cli_args.task_args)

    except LoginFailedException as ex:
        logger.critical(ex)


def task_backup(api, work_dir, task_args):
    logger = logging.getLogger('task_backup')
    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py backup', description='{header}\nBackup task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                             help='''One or more tags for selecting items to be backed up. 
                                     Multiple tags should be separated by space.
                                     Available tags: {tag_options}. Special tag '{all}' selects all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    backup_args = task_parser.parse_args(task_args)

    logger.info('Starting backup task: vManage URL: "%s" > Work_dir: "%s"', api.base_url, work_dir)
    for _, title, index_cls, item_cls in catalog_entries(*backup_args.tags):
        try:
            # Process index class
            item_index = index_cls(api.get(index_cls.api_path.get))
            if item_index.save(work_dir):
                logger.info('Saved %s index', title)
        except requests.exceptions.HTTPError:
            logger.info('Skipped %s, item not supported by this vManage', title)
            continue

        for item_id, item_name in item_index:
            try:
                # Process item class
                item_obj = item_cls(api.get(item_cls.api_path.get, item_id))
                if item_obj.save(work_dir, item_name=item_name, item_id=item_id):
                    logger.info('Done %s %s', title, item_name)

                # Special case for DeviceTemplateAttached/DeviceTemplateValues
                if isinstance(item_obj, DeviceTemplate):
                    devices_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id))
                    if devices_attached.save(work_dir, item_name=item_name, item_id=item_id):
                        logger.info('Done %s %s attached devices', title, item_name)
                    else:
                        logger.info('Skipped %s %s attached devices, none found', title, item_name)
                        continue

                    uuids = list(devices_attached)
                    template_values = DeviceTemplateValues(
                        api.post(DeviceTemplateValues.api_params(item_id, uuids), DeviceTemplateValues.api_path.post)
                    )
                    if template_values.save(work_dir, item_name=item_name, item_id=item_id):
                        logger.info('Done %s %s values', title, item_name)
            except requests.exceptions.HTTPError as ex:
                logger.error('Failed backup %s %s: %s', title, item_name, ex)

    logger.info('Backup task complete')


# TODO: Restore device attachments and values
# TODO: Option to restore only templates with some reference
# TODO: Look at last-updated to decide whether to push a new item or not. Keep skip by default but include option to ovewrite
def task_restore(api, default_work_dir, task_args):
    logger = logging.getLogger('task_restore')
    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py restore', description='{header}\nRestore task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('--dryrun', action='store_true',
                             help='Restore dry-run mode. Items to be restored are only listed, not pushed to vManage.')
    task_parser.add_argument('--update', action='store_true',
                             help='Update vManage item if it is different than a saved item with the same name. By default items with the same name are not restored.')
    task_parser.add_argument('--workdir', metavar='<workdir>', nargs='?', default=default_work_dir, const=default_work_dir,
                             help='''Directory used to source items to be restored (default will be "{default_dir}").
                                  '''.format(default_dir=default_work_dir))
    task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                             help='''Tag for selecting items to be restored. 
                                     Items that are dependencies of the specified tag are automatically included.
                                     Available tags: {tag_options}. Special tag '{all}' selects all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    restore_args = task_parser.parse_args(task_args)

    logger.info('Starting restore task%s: Work_dir: "%s" > vManage URL: "%s"',
                ', DRY-RUN mode' if restore_args.dryrun else '', restore_args.workdir, api.base_url)

    logger.info('Loading existing items from target vManage')
    # existing_items is {<hash of index_cls>: {<item_name>: (<item_id>,<item_ts)}}
    existing_items = {}
    for _, _, index_cls, item_cls in catalog_entries(CATALOG_TAG_ALL):
        try:
            item_index = index_cls(api.get(index_cls.api_path.get))
        except requests.exceptions.HTTPError:
            # Item not supported by this vManage, just move on
            continue
        existing_items[hash(index_cls)] = {item_name: item_id for item_id, item_name in item_index}

    # id_mapping is {<old_id>: <new_id>}, used to replace old item ids with new ids
    id_mapping = {}

    logger.info('Identifying items to be pushed')
    # restore_list is [ (<title>, <index_cls>, [(<item_id>, <item_obj>, <id_on_target>), ...]), ...]
    restore_list = []
    for tag in sequenced_tags(restore_args.tag):
        logger.info('Inspecting %s items', tag)

        for title, index_cls, loaded_items in iter_saved_items(restore_args.workdir, tag):
            target_items = existing_items.get(hash(index_cls))
            if target_items is None:
                logger.warning('Will skip %s, item not supported by target vManage', title)
                continue

            restore_items = []
            for item_id, item_obj in loaded_items:
                id_on_target = None
                target_id = target_items.get(item_obj.name)

                if target_id is not None:
                    # Item already exists on target vManage, item id on target will be used
                    if item_id != target_id:
                        id_mapping[item_id] = target_id
                    # TODO: Implement diff check
                    if restore_args.update and False and not item_obj.is_readonly:
                        # Existing item on target vManage will be updated
                        id_on_target = target_id
                        logger.info('Will update %s %s', title, item_obj.name)
                    else:
                        # Existing item on target vManage will be used as is
                        logger.info('Will skip %s %s', title, item_obj.name)
                        continue

                if item_obj.is_readonly:
                    logger.warning('Will skip %s %s, factory default item', title, item_obj.name)
                    continue

                restore_items.append((item_id, item_obj, id_on_target))

            if len(restore_items) > 0:
                restore_list.append((title, index_cls, restore_items))

    if len(restore_list) > 0:
        logger.info('%sPushing items to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')
        for title, index_cls, item_list in restore_list:
            pushed_item_dict = {}
            for item_id, item_obj, id_on_target in item_list:
                op_info = 'Update' if id_on_target is not None else 'Create'

                if restore_args.dryrun:
                    logger.info('DRY-RUN: %s %s %s', op_info, title, item_obj.name)
                    continue

                try:
                    if id_on_target is None:
                        # Not using item id returned from post as some items' post return empty (e.g. local policies)
                        api.post(item_obj.post_data(id_mapping), item_obj.api_path.post)
                        pushed_item_dict[item_obj.name] = item_id
                    else:
                        api.put(item_obj.put_data(id_mapping, id_on_target), item_obj.api_path.put, id_on_target)

                    logger.info('Done: %s %s %s', op_info, title, item_obj.name)
                except requests.exceptions.HTTPError as ex:
                    logger.error('Failed %s %s %s: %s', op_info, title, item_obj.name, ex)

            # Read new ids on target and update id_mapping
            target_index = {item_name: item_id for item_id, item_name in index_cls(api.get(index_cls.api_path.get))}
            for item_name, old_item_id in pushed_item_dict.items():
                id_mapping[old_item_id] = target_index[item_name]
    else:
        logger.info('%sNo items to push to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')

    logger.info('Restore task complete')


def iter_saved_items(work_dir, tag):
    """
    Return an iterator of config items loaded from work_dir, matching tag
    :param tag: Tag used to match which catalog entries to retrieve
    :param work_dir: Directory containing the backup files from a vManage node
    :return: Iterator of (<catalog title>, <index_cls>, <loaded_items>)
    """
    def index_list_exist(index_list_entry):
        return index_list_entry[0] is not None

    def saved_items_entry(index_list, catalog_entry):
        items = ((item_id, catalog_entry.item_cls.load(work_dir, item_name=item_name, item_id=item_id))
                 for item_id, item_name in index_list)
        loaded_items = ((item_id, item_obj) for item_id, item_obj in items if item_obj is not None)
        return catalog_entry.title, catalog_entry.index_cls, loaded_items

    index_list_entries = ((entry.index_cls.load(work_dir), entry) for entry in catalog_entries(tag))

    return starmap(saved_items_entry, filter(index_list_exist, index_list_entries))


def task_delete(api, work_dir, task_args):
    logger = logging.getLogger('task_delete')
    # Parse task_args
    task_parser = argparse.ArgumentParser(prog='sastre.py delete', description='{header}\nDelete task:'.format(header=__doc__),
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    task_parser.add_argument('--regexp', metavar='<regexp>', nargs='?',
                             help='Regular expression used to match item names to be deleted, within selected tags.')
    task_parser.add_argument('--dryrun', action='store_true',
                             help='Delete dry-run mode. Items matched for removal are only listed, not deleted.')
    task_parser.add_argument('--detach', action='store_true',
                             help='Detach devices from templates before deleting items.')
    task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                             help='''Tag for selecting items to be deleted. 
                                     Available tags: {tag_options}. Special tag '{all}' selects all items.
                                  '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
    delete_args = task_parser.parse_args(task_args)

    logger.info('Starting delete task%s: vManage URL: "%s"',
                ', DRY-RUN mode' if delete_args.dryrun else '', api.base_url)

    # Need to detach vEdges first, then vSmart, if all vEdges are detached
    # From index, separate vsmart from other deviceTypes Detatch end wait non-vsmart first, then vsmart
    if delete_args.detach:
        action_list = []    # [(<action_worker>, <title>, <item_name>), ...]
        for _, title, index_cls, item_cls in catalog_entries('template_device'):
            if not issubclass(item_cls, DeviceTemplate):
                continue

            try:
                item_index = index_cls(api.get(index_cls.api_path.get))
            except requests.exceptions.HTTPError:
                # Item not supported by this vManage, just move on
                continue

            for item_id, item_name in item_index:
                t_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id))

                if t_attached.is_empty:
                    continue

                uuids, personalities = zip(*t_attached)
                # Personalities for all devices attached to the same template are always the same
                action_worker = DeviceModeCli(api.post(DeviceModeCli.api_params(personalities[0], *uuids),
                                                       DeviceModeCli.api_path.post)) if not delete_args.dryrun else None

                action_list.append((action_worker, title, item_name))

        wait_actions(api, action_list, 'detach devices', delete_args.dryrun)

    # Tag list is visited in reverse order from sequenced_tags so that top-level items are removed first
    tag_list = list(sequenced_tags(delete_args.tag)) if delete_args.tag == CATALOG_TAG_ALL else [delete_args.tag, ]
    for tag in reversed(tag_list):
        logger.info('Inspecting %s items', tag)
        for _, title, index_cls, item_cls in catalog_entries(tag):
            try:
                item_index = index_cls(api.get(index_cls.api_path.get))
            except requests.exceptions.HTTPError:
                logger.info('Skipped %s, item not supported by this vManage', title)
                continue

            for item_id, item_name in item_index:
                if delete_args.regexp is None or re.match(delete_args.regexp, item_name):
                    item_obj = item_cls(api.get(item_cls.api_path.get, item_id))
                    if item_obj.is_readonly:
                        continue

                    if delete_args.dryrun:
                        logger.info('DRY-RUN: %s %s', title, item_name)
                        continue

                    if api.delete(item_cls.api_path.delete, item_id):
                        logger.info('Done %s %s', title, item_name)
                    else:
                        logger.warning('Failed deleting %s %s', title, item_name)

    logger.info('Delete task complete')


def wait_actions(api, action_list, action_info, is_dryrun=False):
    """
    Wait for actions in action_list to complete
    :param api: Instance of Rest API
    :param action_list: [(<action_worker>, <title>, <item_name>), ...]
    :param action_info: String with details to be added to the logging messages
    :param is_dryrun: True if in dry-run mode, False otherwise
    :return: True if all actions completed with success. False otherwise.
    """
    logger = logging.getLogger('wait_actions')
    result_list = []
    time_budget = Config.ACTION_TIMEOUT
    for action_worker, title, item_name in action_list:
        if is_dryrun:
            logger.info('DRY-RUN: %s %s %s', title, item_name, action_info)
            continue

        while True:
            action = ActionStatus(api.get(ActionStatus.api_path.get, action_worker.uuid))
            if action.is_completed:
                if action.is_successful:
                    logger.info('Done %s %s %s', title, item_name, action_info)
                    result_list.append(True)
                else:
                    logger.warning('Failed %s %s %s', title, item_name, action_info)
                    result_list.append(False)
                break

            time_budget -= Config.ACTION_INTERVAL
            if time_budget > 0:
                logger.info('Waiting %s', action_info)
                time.sleep(Config.ACTION_INTERVAL)
            else:
                logger.warning('Time limit expired while waiting %s %s %s', title, item_name, action_info)
                result_list.append(False)
                break

    return all(result_list)


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
                'Invalid task. Options are: {options}'.format(options=cls.options())
            )
        return cls.task_options.get(task_string)

    @classmethod
    def options(cls):
        return ', '.join(cls.task_options)


class TagOptions:
    tag_options = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_string):
        if tag_string not in cls.tag_options:
            raise argparse.ArgumentTypeError(
                '"{}" is not a valid tag. Available tags: {}.'.format(tag_string, cls.options())
            )
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
