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
from itertools import starmap
import requests.exceptions
from lib.config_items import *
from lib.rest_api import Rest, LoginFailedException
from lib.catalog import catalog_size, catalog_entries, CATALOG_TAG_ALL, ordered_tags
from lib.utils import TaskOptions, TagOptions, ShowOptions, directory_type, regex_type, uuid_type, EnvVar
from lib.task_common import Task, Table

__author__     = "Marcelo Reis"
__copyright__  = "Copyright (c) 2019 by Cisco Systems, Inc. All rights reserved."
__version__    = "0.14"
__maintainer__ = "Marcelo Reis"
__email__      = "mareis@cisco.com"
__status__     = "Development"

# TODO: 19.2 support
# TODO: Allow for selective attach/detach
# TODO: Add support to re-attach cli templates
# TODO: Allow renaming of backed up items before uploading
# TODO: Be able to provide external csv files for the attachment
# TODO: Look at diff to decide whether to push a new item or not. Keep skip by default but include option to overwrite


class Config:
    VMANAGE_DEFAULT_PORT = '8443'
    REST_DEFAULT_TIMEOUT = 300


def main(cli_args):
    base_url = 'https://{address}:{port}'.format(address=cli_args.address, port=cli_args.port)
    default_work_dir = 'node_{address}'.format(address=cli_args.address)

    parsed_task_args = cli_args.task.parser(default_work_dir, cli_args.task_args)
    try:
        with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
            # Dispatch to the appropriate task handler
            cli_args.task.runner(api, parsed_task_args)

    except (LoginFailedException, FileNotFoundError) as ex:
        logging.getLogger(__name__).critical(ex)


@TaskOptions.register('backup')
class TaskBackup(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py backup',
                                              description='{header}\nBackup task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--workdir', metavar='<directory>', default=default_work_dir,
                                 help='''Directory used to save the backup (default will be "{default_dir}").
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='''One or more tags for selecting items to be backed up. 
                                         Multiple tags should be separated by space.
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, api, backup_args):
        cls.log_info('Starting backup task: vManage URL: "%s" > Work_dir: "%s"', api.base_url, backup_args.workdir)
        for _, title, index_cls, item_cls in catalog_entries(*backup_args.tags):
            try:
                # Process index class
                item_index = index_cls(api.get(index_cls.api_path.get))
                if item_index.save(backup_args.workdir):
                    cls.log_info('Saved %s index', title)
            except requests.exceptions.HTTPError:
                cls.log_debug('Skipped %s, item not supported by this vManage', title)
                continue

            for item_id, item_name in item_index:
                log_params = (title, item_name)
                try:
                    # Process item class
                    item_obj = item_cls(api.get(item_cls.api_path.get, item_id))
                    if item_obj.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                        cls.log_info('Done %s %s', *log_params)

                    # Special case for DeviceTemplateAttached/DeviceTemplateValues
                    if isinstance(item_obj, DeviceTemplate):
                        devices_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, item_id))
                        if devices_attached.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                            cls.log_info('Done %s %s attached devices', *log_params)
                        else:
                            cls.log_debug('Skipped %s %s attached devices, none found', *log_params)
                            continue

                        uuids = [uuid for uuid, personality in devices_attached]
                        template_values = DeviceTemplateValues(
                            api.post(DeviceTemplateValues.api_params(item_id, uuids), DeviceTemplateValues.api_path.post)
                        )
                        if template_values.save(backup_args.workdir, item_name=item_name, item_id=item_id):
                            cls.log_info('Done %s %s values', *log_params)
                except requests.exceptions.HTTPError as ex:
                    cls.log_error('Failed backup %s %s: %s', *log_params, ex)

        cls.log_info('Backup task completed %s', cls.outcome('successfully', 'with caveats: {tally}'))


@TaskOptions.register('restore')
class TaskRestore(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py restore',
                                              description='{header}\nRestore task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--workdir', metavar='<directory>', type=directory_type,
                                 default=default_work_dir,
                                 help='''Directory used to source items to be restored (default will be "{default_dir}").
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Restore dry-run mode. Items to be restored are only listed, not pushed to vManage.')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression used to match item names to be restored, within selected tags.')
        # task_parser.add_argument('--update', action='store_true',
        #                          help='Update vManage item if it is different than a saved item with the same name. '
        #                               'By default items with the same name are not restored.')
        task_parser.add_argument('--attach', action='store_true',
                                 help='Attach devices to templates and activate vSmart policy after restoring items.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='''Tag for selecting items to be restored. 
                                         Items that are dependencies of the specified tag are automatically included.
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, api, restore_args):
        cls.log_info('Starting restore task%s: Work_dir: "%s" > vManage URL: "%s"',
                    ', DRY-RUN mode' if restore_args.dryrun else '', restore_args.workdir, api.base_url)

        cls.log_info('Loading existing items from target vManage')
        # existing_items is {<hash of index_cls>: {<item_name>: <item_id>}}
        existing_items = {
            hash(type(index)): {item_name: item_id for item_id, item_name in index}
            for _, title, index, item_cls in cls.index_iter(catalog_entries(CATALOG_TAG_ALL), api)
        }

        cls.log_info('Identifying items to be pushed')
        id_mapping = {}         # {<old_id>: <new_id>}, used to replace old item ids with new ids
        restore_list = []       # [ (<title>, <index_cls>, [(<item_id>, <item_obj>, <id_on_target>), ...]), ...]
        dependency_set = set()  # {<item_id>, ...}
        match_set = set()       # {<item_id>, ...}
        for tag in ordered_tags(restore_args.tag):
            cls.log_info('Inspecting %s items', tag)

            for title, index_cls, loaded_items in saved_items_iter(restore_args.workdir, tag):
                target_items = existing_items.get(hash(index_cls))
                if target_items is None:
                    # Logging at warning level because the backup files did have this item
                    cls.log_warning('Will skip %s, item not supported by target vManage', title)
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
                        cls.log_debug('Will skip %s %s, item already on target vManage', title, item_obj.name)
                        continue

                    if item_obj.is_readonly:
                        cls.log_warning('Will skip %s %s, factory default item', title, item_obj.name)
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
            cls.log_info('%sPushing items to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')
            for title, index_cls, item_list in reversed(restore_list):
                pushed_item_dict = {}
                for item_id, item_obj, id_on_target in item_list:
                    op_info = 'Update' if id_on_target is not None else 'Create'
                    reason = ' (dependency)' if item_id in dependency_set - match_set else ''

                    if restore_args.dryrun:
                        cls.log_info('DRY-RUN: %s %s %s%s', op_info, title, item_obj.name, reason)
                        continue

                    try:
                        if id_on_target is None:
                            # Not using item id returned from post because post can return empty (e.g. local policies)
                            api.post(item_obj.post_data(id_mapping), item_obj.api_path.post)
                            pushed_item_dict[item_obj.name] = item_id
                        else:
                            api.put(item_obj.put_data(id_mapping, id_on_target), item_obj.api_path.put, id_on_target)

                        cls.log_info('Done: %s %s %s%s', op_info, title, item_obj.name, reason)
                    except requests.exceptions.HTTPError as ex:
                        cls.log_error('Failed %s %s %s%s: %s', op_info, title, item_obj.name, reason, ex)

                # Read new ids on target and update id_mapping
                target_index = {item_name: item_id for item_id, item_name in index_cls(api.get(index_cls.api_path.get))}
                for item_name, old_item_id in pushed_item_dict.items():
                    id_mapping[old_item_id] = target_index[item_name]
        else:
            cls.log_info('%sNo items to push to vManage', 'DRY-RUN: ' if restore_args.dryrun else '')

        if restore_args.attach and not restore_args.dryrun:
            target_templates = {item_name: item_id
                                for item_id, item_name in DeviceTemplateIndex(api.get(DeviceTemplateIndex.api_path.get))}
            saved_template_index = DeviceTemplateIndex.load(restore_args.workdir)
            if saved_template_index is None:
                raise FileNotFoundError('DeviceTemplateIndex file not found')
            # Attach WAN Edges
            target_wan_edge_set = {uuid for uuid, _ in EdgeInventory(api.get(EdgeInventory.api_path.get))}
            action_list = cls.attach_template(api, saved_template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart),
                                              restore_args.workdir, target_templates, target_wan_edge_set)
            if len(action_list) == 0:
                cls.log_info('No WAN Edge attachments needed')
            else:
                cls.wait_actions(api, action_list, 'attaching WAN Edges')
            # Attach vSmarts
            target_vsmart_set = {uuid for uuid, _ in ControlInventory(api.get(ControlInventory.api_path.get)).filtered_iter(ControlInventory.is_vsmart)}
            action_list = cls.attach_template(api, saved_template_index.filtered_iter(DeviceTemplateIndex.is_vsmart),
                                              restore_args.workdir, target_templates, target_vsmart_set)
            if len(action_list) == 0:
                cls.log_info('No vSmart attachments needed')
            else:
                cls.wait_actions(api, action_list, 'attaching vSmarts')
            # Activate vSmart policy
            action_list = []
            try:
                PolicyVsmartStatus(api.get(PolicyVsmartStatus.api_path.get)).raise_for_status()
            except (requests.exceptions.HTTPError, PolicyVsmartStatusException):
                cls.log_debug('vSmarts not in vManage mode or otherwise not ready to have policy activated')
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
                cls.log_info('No vSmart policy to activate')
            else:
                cls.wait_actions(api, action_list, 'activating vSmart policy')

        cls.log_info('Restore task completed %s', cls.outcome('successfully', 'with caveats: {tally}'))


@TaskOptions.register('delete')
class TaskDelete(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py delete',
                                              description='{header}\nDelete task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='Delete dry-run mode. Items matched for removal are only listed, not deleted.')
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression used to match item names to be deleted, within selected tags.')
        task_parser.add_argument('--detach', action='store_true',
                                 help='USE WITH CAUTION! Detach devices from templates and deactivate vSmart policy '
                                      'before deleting items. This allows deleting items that are dependencies.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='''Tag for selecting items to be deleted. 
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, api, delete_args):
        cls.log_info('Starting delete task%s: vManage URL: "%s"',
                     ', DRY-RUN mode' if delete_args.dryrun else '', api.base_url)

        if delete_args.detach and not delete_args.dryrun:
            template_index = DeviceTemplateIndex(api.get(DeviceTemplateIndex.api_path.get))
            # Detach WAN Edges
            action_list = cls.detach_template(api, template_index, DeviceTemplateIndex.is_not_vsmart)
            if len(action_list) == 0:
                cls.log_info('No WAN Edge attached')
            else:
                cls.wait_actions(api, action_list, 'detaching WAN Edges')
            # Deactivate vSmart policy
            action_list = []
            for item_id, item_name in PolicyVsmartIndex(api.get(PolicyVsmartIndex.api_path.get)).active_policy_iter():
                action_list.append(
                    (PolicyVsmartDeactivate(api.post({}, PolicyVsmartDeactivate.api_path.post, item_id)), item_name)
                )
            if len(action_list) == 0:
                cls.log_info('No vSmart policy activated')
            else:
                cls.wait_actions(api, action_list, 'deactivating vSmart policy')
            # Detach vSmarts
            action_list = cls.detach_template(api, template_index, DeviceTemplateIndex.is_vsmart)
            if len(action_list) == 0:
                cls.log_info('No vSmart attached')
            else:
                cls.wait_actions(api, action_list, 'detaching vSmarts')

        for tag in ordered_tags(delete_args.tag, delete_args.tag != CATALOG_TAG_ALL):
            cls.log_info('Inspecting %s items', tag)
            matched_item_iter = (
                (item_name, item_id, item_cls, title)
                for _, title, index, item_cls in cls.index_iter(catalog_entries(tag), api)
                for item_id, item_name in index
                if delete_args.regex is None or re.search(delete_args.regex, item_name)
            )
            for item_name, item_id, item_cls, title in matched_item_iter:
                item_obj = cls.get_item(item_name, item_id, item_cls, api)
                log_params = (title, item_name)
                if item_obj is None:
                    cls.log_warning('Failed retrieving %s %s', *log_params)
                    continue
                if item_obj.is_readonly:
                    continue
                if delete_args.dryrun:
                    cls.log_info('DRY-RUN: %s %s', *log_params)
                    continue

                if api.delete(item_cls.api_path.delete, item_id):
                    cls.log_info('Done %s %s', *log_params)
                else:
                    cls.log_warning('Failed deleting %s %s', *log_params)

        cls.log_info('Delete task completed %s', cls.outcome('successfully', 'with caveats: {tally}'))


@TaskOptions.register('list')
class TaskList(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py list',
                                              description='{header}\nList task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('--workdir', metavar='<directory>', type=directory_type,
                                 help='''If specified the list task will operate locally, on items from this directory,
                                         instead of on target vManage.
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('--regex', metavar='<regex>', type=regex_type,
                                 help='Regular expression used to match item names to retrieve, within selected tags.')
        task_parser.add_argument('--csv', metavar='<filename>',
                                 help='''Instead of printing a table with the list results, export as csv file with
                                         the filename provided.''')
        task_parser.add_argument('tags', metavar='<tag>', nargs='+', type=TagOptions.tag,
                                 help='''One or more tags for selecting groups of items. 
                                         Multiple tags should be separated by space.
                                         Available tags: {tag_options}. Special tag '{all}' selects all items.
                                      '''.format(tag_options=TagOptions.options(), all=CATALOG_TAG_ALL))
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, api, list_args):
        target_info = 'vManage URL: "{url}"'.format(url=api.base_url) if list_args.workdir is None \
                 else 'Work_dir: "{workdir}"'.format(workdir=list_args.workdir)
        cls.log_info('Starting list task: %s', target_info)

        matched_item_iter = (
            (item_name, item_id, tag, title)
            for tag, title, index, item_cls in cls.index_iter(catalog_entries(*list_args.tags), api, list_args.workdir)
            for item_id, item_name in index
            if list_args.regex is None or re.search(list_args.regex, item_name)
        )
        results = Table('Name', 'ID', 'Tag', 'Description')
        results.extend(matched_item_iter)
        cls.log_info('List criteria matched %s items', len(results))

        if len(results) > 0:
            print_buffer = []
            print_buffer.extend(results.pretty_iter())

            if list_args.csv is not None:
                results.save(list_args.csv)
                cls.log_info('Table exported as %s', list_args.csv)
            else:
                print('\n'.join(print_buffer))

        cls.log_info('List task completed %s', cls.outcome('successfully', 'with caveats: {tally}'))


@TaskOptions.register('show-template')
class TaskShowTemplate(Task):
    @staticmethod
    def parser(default_work_dir, task_args):
        task_parser = argparse.ArgumentParser(prog='sastre.py show-template',
                                              description='{header}\nShow template task:'.format(header=__doc__),
                                              formatter_class=argparse.RawDescriptionHelpFormatter)
        task_parser.add_argument('option', metavar='<option>', type=ShowOptions.option,
                                 help='''Attributes to show. Available options: {show_options}.
                                      '''.format(show_options=ShowOptions.options()))
        task_parser.add_argument('--workdir', metavar='<directory>', type=directory_type,
                                 help='''If specified the show task will operate locally, on items from this directory,
                                         instead of on target vManage.
                                      '''.format(default_dir=default_work_dir))
        task_parser.add_argument('--csv', metavar='<directory>',
                                 help='''Instead of printing tables with the results, export as csv files.
                                         Exported files are saved under the specified directory.''')
        xor_group = task_parser.add_mutually_exclusive_group(required=True)
        xor_group.add_argument('--name', metavar='<name>', help='Device template name.')
        xor_group.add_argument('--id', metavar='<id>', type=uuid_type, help='Device template ID.')
        xor_group.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='Regular expression used to match device template names.')
        return task_parser.parse_args(task_args)

    @classmethod
    def runner(cls, api, show_args):
        target_info = 'vManage URL: "{url}"'.format(url=api.base_url) if show_args.workdir is None \
            else 'Work_dir: "{workdir}"'.format(workdir=show_args.workdir)
        cls.log_info('Starting show task: %s', target_info)

        if show_args.csv is not None:
            os.makedirs(show_args.csv, exist_ok=True)

        # Dispatch to the appropriate show handler
        show_args.option(cls, api, show_args)

        cls.log_info('Show task completed %s', cls.outcome('successfully', 'with caveats: {tally}'))

    @classmethod
    @ShowOptions.register('values')
    def device_template_values(cls, api, show_args):
        def item_matches(item_name, item_id):
            if show_args.id is not None:
                return item_id == show_args.id
            if show_args.name is not None:
                return item_name == show_args.name
            return re.search(show_args.regex, item_name) is not None

        def template_values(template_name, template_id):
            if show_args.workdir is None:
                try:
                    devices_attached = DeviceTemplateAttached(api.get(DeviceTemplateAttached.api_path.get, template_id))
                    uuids = [uuid for uuid, personality in devices_attached]
                    values = DeviceTemplateValues(
                        api.post(DeviceTemplateValues.api_params(template_id, uuids), DeviceTemplateValues.api_path.post)
                    )
                except requests.exceptions.HTTPError as ex:
                    cls.log_error('Failed to retrieve %s values: %s', item_name, ex)
                    values = None
            else:
                values = DeviceTemplateValues.load(show_args.workdir, item_name=template_name, item_id=template_id)
                if values is None:
                    cls.log_debug('Skipped %s. No template values file found.', item_name)

            return values

        print_buffer = []
        matched_item_iter = (
            (item_name, item_id, tag, title)
            for tag, title, index, item_cls in cls.index_iter(catalog_entries('template_device'), api, show_args.workdir)
            for item_id, item_name in index
            if item_matches(item_name, item_id) and issubclass(item_cls, DeviceTemplate)
        )
        for item_name, item_id, tag, title in matched_item_iter:
            attached_values = template_values(item_name, item_id)
            if attached_values is None:
                continue

            cls.log_info('Inspecting %s %s values', title, item_name)
            var_names = attached_values.title_dict()
            for csv_id, csv_name, entry in attached_values:
                print_grp = [
                    'Template {name}, device {device}:'.format(name=item_name, device=csv_name or csv_id)
                ]
                results = Table('Name', 'Value', 'Variable')
                results.extend(
                    (var_names.get(var, '<not found>'), value, var) for var, value in entry.items()
                )
                if len(results) > 0:
                    if show_args.csv is not None:
                        filename = 'template_values_{name}_{id}.csv'.format(name=item_name, id=csv_name or csv_id)
                        results.save(os.path.join(show_args.csv, filename))
                    print_grp.extend(results.pretty_iter())
                print_buffer.append('\n'.join(print_grp))

        if len(print_buffer) > 0:
            if show_args.csv is not None:
                cls.log_info('Exported csv files saved under %s', show_args.csv)
            else:
                print('\n\n'.join(print_buffer))
        else:
            match_type = 'ID' if show_args.id is not None else 'name' if show_args.name is not None else 'regex'
            cls.log_warning('No items found with the %s provided', match_type)


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


if __name__ == '__main__':
    cli_parser = argparse.ArgumentParser(description=__doc__)
    cli_parser.add_argument('-a', '--address', metavar='<vmanage-ip>', action=EnvVar, envvar='VMANAGE_IP',
                            help='vManage IP address, can also be provided via VMANAGE_IP environment variable')
    cli_parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, envvar='VMANAGE_USER',
                            help='username, can also be provided via VMANAGE_USER environment variable')
    cli_parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, envvar='VMANAGE_PASSWORD',
                            help='password, can also be provided via VMANAGE_PASSWORD environment variable')
    cli_parser.add_argument('--port', metavar='<port>', default=Config.VMANAGE_DEFAULT_PORT,
                            help='vManage TCP port number (default is {port})'.format(port=Config.VMANAGE_DEFAULT_PORT))
    cli_parser.add_argument('--timeout', metavar='<timeout>', type=int, default=Config.REST_DEFAULT_TIMEOUT,
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
                'format': '%(asctime)s: %(name)s: %(levelname)s: %(message)s',
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
        # To prevent unwanted debug messages from requests module
        'loggers': {
            'chardet.charsetprober': {
                'level': 'INFO',
            },
        },
    }
    os.makedirs('logs', exist_ok=True)
    logging.config.dictConfig(LOGGING_CONFIG)

    # Entry point
    main(args)
