#! /usr/bin/env python3
"""
Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

"""
import logging
import logging.config
import logging.handlers
import argparse
import os.path
import re
import time
from itertools import starmap
import requests.exceptions
from lib.config_items import *
from lib.rest_api import Rest, LoginFailedException
from lib.catalog import catalog_size, catalog_entries, CATALOG_TAG_ALL, ordered_tags
from lib.utils import Task, TaskOptions, TagOptions, existing_workdir_type, regex_type, EnvVar

__author__     = "Marcelo Reis"
__copyright__  = "Copyright (c) 2019 by Cisco Systems, Inc. All rights reserved."
__version__    = "0.11"
__maintainer__ = "Marcelo Reis"
__email__      = "mareis@cisco.com"
__status__     = "Development"


# TODO: Add tally to task completion messages indicating count of warnings and above items
# TODO: Allow for selective attach/detach
# TODO: Add logging decorator to rest api calls.
# TODO: Add support to re-attach cli templates
# TODO: Allow renaming of backed up items before uploading
# TODO: Be able to provide external csv files for the attachment
# TODO: Look at diff to decide whether to push a new item or not. Keep skip by default but include option to overwrite


class Config:
    VMANAGE_DEFAULT_PORT = '8443'
    REST_DEFAULT_TIMEOUT = 300
    ACTION_INTERVAL = 10
    ACTION_TIMEOUT = 600


def main(cli_args):
    logger = logging.getLogger(__name__)

    base_url = 'https://{address}:{port}'.format(address=cli_args.address, port=cli_args.port)
    default_work_dir = 'node_{address}'.format(address=cli_args.address)

    parsed_task_args = cli_args.task.parser(default_work_dir, cli_args.task_args)
    try:
        with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
            # Dispatch to the appropriate task handler
            cli_args.task.runner(api, parsed_task_args)

    except (LoginFailedException, FileNotFoundError) as ex:
        logger.critical(ex)


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py backup', description='{header}\nBackup task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--workdir', metavar='<workdir>', nargs='?', default=default_work_dir, const=default_work_dir,
                                 help='''Directory used to save the backup (default will be "{default_dir}").
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='''One or more tags for selecting items to be backed up. 
                                         Multiple tags should be separated by space.
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @staticmethod
    def runner(api, backup_args):
        logger = logging.getLogger('task_backup')

        logger.info('Starting backup task: vManage URL: "%s" > Work_dir: "%s"', api.base_url, backup_args.workdir)
        for _, title, index_cls, item_cls in catalog_entries(*backup_args.tags):
            try:
                # Process index class
                item_index = index_cls(api.get(index_cls.api_path.get))
                if item_index.save(backup_args.workdir):
                    logger.info('Saved %s index', title)
            except requests.exceptions.HTTPError:
                logger.debug('Skipped %s, item not supported by this vManage', title)
                continue

            for item_id, item_name in item_index:
                try:
                    # Process item class
                    item_obj = item_cls(api.get(item_cls.api_path.get, item_id))
                    if item_obj.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                        logger.info('Done %s %s', title, item_name)

                    # Special case for DeviceTemplateAttached/DeviceTemplateValues
                    if isinstance(item_obj, DeviceTemplate):
                        devices_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id))
                        if devices_attached.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                            logger.info('Done %s %s attached devices', title, item_name)
                        else:
                            logger.debug('Skipped %s %s attached devices, none found', title, item_name)
                            continue

                        uuids = [uuid for uuid, personality in devices_attached]
                        template_values = DeviceTemplateValues(
                            api.post(DeviceTemplateValues.api_params(item_id, uuids), DeviceTemplateValues.api_path.post)
                        )
                        if template_values.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                            logger.info('Done %s %s values', title, item_name)
                except requests.exceptions.HTTPError as ex:
                    logger.error('Failed backup %s %s: %s', title, item_name, ex)

        logger.info('Backup task complete')


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py restore', description='{header}\nRestore task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Restore dry-run mode. Items to be restored are only listed, not pushed to vManage.')
        task_parser.add_argument('--regex', metavar='<regex>', nargs='?', type=regex_type,
                                 help='Regular expression used to match item names, within selected tags, to be restored.')
        # task_parser.add_argument('--update', action='store_true',
        #                          help='Update vManage item if it is different than a saved item with the same name. '
        #                               'By default items with the same name are not restored.')
        task_parser.add_argument('--attach', action='store_true',
                                 help='Attach devices to templates and activate vSmart policy after restoring items.')
        task_parser.add_argument('--workdir', metavar='<workdir>', nargs='?', type=existing_workdir_type,
                                 default=default_work_dir, const=default_work_dir,
                                 help='''Directory used to source items to be restored (default will be "{default_dir}").
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='''Tag for selecting items to be restored. 
                                         Items that are dependencies of the specified tag are automatically included.
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @staticmethod
    def runner(api, restore_args):
        logger = logging.getLogger('task_restore')
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
        restore_list = []       # [ (<title>, <index_cls>, [(<item_id>, <item_obj>, <id_on_target>), ...]), ...]
        dependency_set = set()  # {<item_id>, ...}
        match_set = set()       # {<item_id>, ...}
        for tag in ordered_tags(restore_args.tag):
            logger.info('Inspecting %s items', tag)

            for title, index_cls, loaded_items in saved_items_iter(restore_args.workdir, tag):
                target_items = existing_items.get(hash(index_cls))
                if target_items is None:
                    # Logging at warning level because the backup files did have this item
                    logger.warning('Will skip %s, item not supported by target vManage', title)
                    continue

                item_list = []
                for item_id, item_obj in loaded_items:
                    # id_on_target will be used in the future for the --update function
                    id_on_target = None
                    target_id = target_items.get(item_obj.name)

                    if target_id is not None:
                        # Item already exists on target vManage, item id from target will be used
                        if item_id != target_id:
                            id_mapping[item_id] = target_id

                        # Existing item on target vManage will be used as is
                        logger.debug('Will skip %s %s, item already on target vManage', title, item_obj.name)
                        continue

                    if item_obj.is_readonly:
                        logger.warning('Will skip %s %s, factory default item', title, item_obj.name)
                        continue

                    item_matches = (
                        (restore_args.tag == CATALOG_TAG_ALL or restore_args.tag == tag) and
                        (restore_args.regex is None or re.search(restore_args.regex, item_obj.name))
                    )
                    if item_matches:
                        match_set.add(item_id)
                    if item_matches or item_id in dependency_set:
                        item_list.append((item_id, item_obj, id_on_target))
                        dependency_set.update(item_obj.id_references_set)

                if len(item_list) > 0:
                    restore_list.append((title, index_cls, item_list))

        if len(restore_list) > 0:
            logger.info('%sPushing items to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')
            for title, index_cls, item_list in reversed(restore_list):
                pushed_item_dict = {}
                for item_id, item_obj, id_on_target in item_list:
                    op_info = 'Update' if id_on_target is not None else 'Create'
                    reason = ' (dependency)' if item_id in dependency_set - match_set else ''

                    if restore_args.dryrun:
                        logger.info('DRY-RUN: %s %s %s%s', op_info, title, item_obj.name, reason)
                        continue

                    try:
                        if id_on_target is None:
                            # Not using item id returned from post because post can return empty (e.g. local policies)
                            api.post(item_obj.post_data(id_mapping), item_obj.api_path.post)
                            pushed_item_dict[item_obj.name] = item_id
                        else:
                            api.put(item_obj.put_data(id_mapping, id_on_target), item_obj.api_path.put, id_on_target)

                        logger.info('Done: %s %s %s%s', op_info, title, item_obj.name, reason)
                    except requests.exceptions.HTTPError as ex:
                        logger.error('Failed %s %s %s%s: %s', op_info, title, item_obj.name, reason, ex)

                # Read new ids on target and update id_mapping
                target_index = {item_name: item_id for item_id, item_name in index_cls(api.get(index_cls.api_path.get))}
                for item_name, old_item_id in pushed_item_dict.items():
                    id_mapping[old_item_id] = target_index[item_name]
        else:
            logger.info('%sNo items to push to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')

        if restore_args.attach and not restore_args.dryrun:
            target_templates = {item_name: item_id
                                for item_id, item_name in DeviceTemplateIndex(api.get(DeviceTemplateIndex.api_path.get))}
            saved_template_index = DeviceTemplateIndex.load(restore_args.workdir)
            if saved_template_index is None:
                raise FileNotFoundError('DeviceTemplateIndex file not found')
            # Attach WAN Edges
            target_wan_edge_set = {uuid for uuid, _ in EdgeInventory(api.get(EdgeInventory.api_path.get))}
            action_list = attach_template(api, saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart),
                                          restore_args.workdir, target_templates, target_wan_edge_set)
            if len(action_list) == 0:
                logger.info('No WAN Edge attachments needed')
            else:
                wait_actions(api, action_list, 'attaching WAN Edges')
            # Attach vSmarts
            target_vsmart_set = {uuid for uuid, _ in ControlInventory(api.get(ControlInventory.api_path.get)).filtered_iter(ControlInventory.is_vsmart)}
            action_list = attach_template(api, saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart),
                                          restore_args.workdir, target_templates, target_vsmart_set)
            if len(action_list) == 0:
                logger.info('No vSmart attachments needed')
            else:
                wait_actions(api, action_list, 'attaching vSmarts')
            # Activate vSmart policy
            action_list = []
            try:
                PolicyVsmartStatus(api.get(PolicyVsmartStatus.api_path.get)).raise_for_status()
            except (requests.exceptions.HTTPError, PolicyVsmartStatusException):
                logger.debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
            else:
                target_vsmart_policies = {item_name: item_id for item_id, item_name in
                                          PolicyVsmartIndex(api.get(PolicyVsmartIndex.api_path.get))}
                for saved_id, saved_name in PolicyVsmartIndex.load(restore_args.workdir).active_policy_iter():
                    target_id = target_vsmart_policies.get(saved_name)
                    if target_id is None:
                        continue
                    action_list.append(
                        (PolicyVsmartActivate(api.post({}, PolicyVsmartActivate.api_path.post, target_id)), saved_name)
                    )
            if len(action_list) == 0:
                logger.info('No vSmart policy to activate')
            else:
                wait_actions(api, action_list, 'activating vSmart policy')

        logger.info('Restore task complete')


@TaskOptions.register('delete')
class TaskDelete(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py delete', description='{header}\nDelete task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Delete dry-run mode. Items matched for removal are only listed, not deleted.')
        task_parser.add_argument('--regex', metavar='<regex>', nargs='?', type=regex_type,
                                 help='Regular expression used to match item names, within selected tags, to be deleted.')
        task_parser.add_argument('--detach', action='store_true',
                                 help='USE WITH CAUTION! Detach devices from templates and deactivate vSmart policy '
                                      'before deleting items. This allows deleting items that are dependencies.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='''Tag for selecting items to be deleted. 
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @staticmethod
    def runner(api, delete_args):
        logger = logging.getLogger('task_delete')
        logger.info('Starting delete task%s: vManage URL: "%s"',
                    ', DRY-RUN mode' if delete_args.dryrun else '', api.base_url)

        if delete_args.detach and not delete_args.dryrun:
            template_index = DeviceTemplateIndex(api.get(DeviceTemplateIndex.api_path.get))
            # Detach WAN Edges
            action_list = detach_template(api, template_index, DeviceTemplateIndex.is_not_vsmart)
            if len(action_list) == 0:
                logger.info('No WAN Edge attached')
            else:
                wait_actions(api, action_list, 'detaching WAN Edges')
            # Deactivate vSmart policy
            action_list = []
            for item_id, item_name in PolicyVsmartIndex(api.get(PolicyVsmartIndex.api_path.get)).active_policy_iter():
                action_list.append(
                    (PolicyVsmartDeactivate(api.post({}, PolicyVsmartDeactivate.api_path.post, item_id)), item_name)
                )
            if len(action_list) == 0:
                logger.info('No vSmart policy activated')
            else:
                wait_actions(api, action_list, 'deactivating vSmart policy')
            # Detach vSmarts
            action_list = detach_template(api, template_index, DeviceTemplateIndex.is_vsmart)
            if len(action_list) == 0:
                logger.info('No vSmart attached')
            else:
                wait_actions(api, action_list, 'detaching vSmarts')

        for tag in ordered_tags(delete_args.tag, delete_args.tag != CATALOG_TAG_ALL):
            logger.info('Inspecting %s items', tag)
            for _, title, index_cls, item_cls in catalog_entries(tag):
                try:
                    item_index = index_cls(api.get(index_cls.api_path.get))
                except requests.exceptions.HTTPError:
                    logger.debug('Skipped %s, item not supported by this vManage', title)
                    continue

                for item_id, item_name in item_index:
                    if delete_args.regex is None or re.search(delete_args.regex, item_name):
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


def saved_items_iter(work_dir, tag):
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


def attach_template(api, saved_template_iter, work_dir, target_template_dict, target_uuid_set):
    """
    :param api: Instance of Rest API
    :param saved_template_iter: Iterator over saved templates to be inspected
    :param work_dir: Directory containing saved items
    :param target_template_dict: Templates on target node: {<template name>: <template id> ...}
    :param target_uuid_set: Set of existing device uuids on target node
    :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
    """
    logger = logging.getLogger('attach_template')
    action_list = []
    for saved_id, saved_name in saved_template_iter:
        logger.debug('Inspecting template %s', saved_name)
        saved_values = DeviceTemplateValues.load(work_dir, item_name=saved_name, item_id=saved_id)
        if saved_values is None:
            logger.error('Could not open %s backup file. ID: %s', saved_name, saved_id)
            continue
        if saved_values.is_empty:
            logger.debug('Skip, saved template has no attachments')
            continue

        target_id = target_template_dict.get(saved_name)
        if target_id is None:
            logger.debug('Skip, saved template is not on target node')
            continue

        target_attached_uuid_set = {
            uuid for uuid, _ in DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, target_id))
        }

        # Limit input values to uuids on target vManage that are not yet attached
        input_values = saved_values.input_list(target_uuid_set - target_attached_uuid_set)
        if len(input_values) == 0:
            logger.debug('Skip, no further devices to attach')
            continue

        action_worker = DeviceTemplateAttach(
            api.post(DeviceTemplateAttach.api_params(target_id, input_values), DeviceTemplateAttach.api_path.post)
        )
        action_list.append((action_worker, saved_name))
        logger.debug('Template attach requested')

    return action_list


def detach_template(api, template_index, filter_fn):
    """
    :param api: Instance of Rest API
    :param template_index: Instance of DeviceTemplateIndex
    :param filter_fn: Function used to filter elements to be returned
    :return: List of worker actions to monitor [(<action_worker>, <template_name>), ...]
    """
    action_list = []
    for item_id, item_name in template_index.filtered_iter(filter_fn):
        devices_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id))

        uuids, personalities = zip(*devices_attached)
        # Personalities for all devices attached to the same template are always the same
        action_worker = DeviceModeCli(
            api.post(DeviceModeCli.api_params(personalities[0], *uuids), DeviceModeCli.api_path.post)
        )
        action_list.append((action_worker, item_name))

    return action_list


def wait_actions(api, action_list, log_context):
    """
    Wait for actions in action_list to complete
    :param api: Instance of Rest API
    :param action_list: [(<action_worker>, <action_info>), ...]. Where <action_worker> is an instance of ApiItem and
                        <action_info> is a str with information about the action.
    :param log_context: String providing context to log messages
    :return: True if all actions completed with success. False otherwise.
    """
    def upper_first(input_string):
        return input_string[0].upper()+input_string[1:] if len(input_string) > 0 else ''
    
    logger = logging.getLogger('wait_actions')
    logger.info(upper_first(log_context))
    result_list = []
    time_budget = Config.ACTION_TIMEOUT
    for action_worker, action_info in action_list:
        while True:
            action = ActionStatus(api.get(ActionStatus.api_path.get, action_worker.uuid))
            if action.is_completed:
                if action.is_successful:
                    logger.info('Done %s', action_info)
                    result_list.append(True)
                else:
                    logger.warning('Failed %s', action_info)
                    result_list.append(False)
                break

            time_budget -= Config.ACTION_INTERVAL
            if time_budget > 0:
                logger.info('Waiting...')
                time.sleep(Config.ACTION_INTERVAL)
            else:
                logger.warning('Wait time limit expired')
                result_list.append(False)
                break

    result = all(result_list)
    if result:
        logger.info('Done %s', log_context)
    else:
        logger.warning('Failed %s', log_context)

    return result


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
    LOGGING_CONFIG = {
        'version': 1,
        'formatters': {
            'simple': {
                'format': '%(levelname)s: %(message)s',
            },
            'detailed': {
                'format': '%(name)s: %(asctime)s: %(levelname)s: %(message)s',
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO' if args.verbose else 'WARN',
                'formatter': 'simple',
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'logs/sastre.log',
                'backupCount': 5,
                'maxBytes': 102400,
                'level': 'DEBUG',
                'formatter': 'detailed',
            },
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
        },

    }
    os.makedirs('logs', exist_ok=True)
    logging.config.dictConfig(LOGGING_CONFIG)

    # Entry point
    main(args)
