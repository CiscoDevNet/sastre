import argparse
from typing import Union, Optional
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.catalog import catalog_iter, CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.base.models_vmanage import DeviceTemplateIndex
from cisco_sdwan.tasks.utils import TaskOptions, TagOptions, regex_type
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException


@TaskOptions.register('delete')
class TaskDelete(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nDelete task:')
        task_parser.prog = f'{task_parser.prog} delete'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        mutex = task_parser.add_mutually_exclusive_group()
        mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names to delete, within selected tags.')
        mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                           help='regular expression matching item names NOT to delete, within selected tags.')
        task_parser.add_argument('--dryrun', action='store_true',
                                 help='dry-run mode. Items matched for removal are listed but not deleted.')
        task_parser.add_argument('--detach', action='store_true',
                                 help='USE WITH CAUTION! Detach devices from templates and deactivate vSmart policy '
                                      'before deleting items. This allows deleting items that are associated with '
                                      'attached templates and active policies.')
        task_parser.add_argument('tag', metavar='<tag>', type=TagOptions.tag,
                                 help='tag for selecting items to be deleted. Available tags: '
                                      f'{TagOptions.options()}. Special tag "{CATALOG_TAG_ALL}" selects all items.')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info('Starting delete%s: vManage URL: "%s"',
                      ', DRY-RUN mode' if parsed_args.dryrun else '', api.base_url)
        log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''

        if parsed_args.detach:
            try:
                template_index = DeviceTemplateIndex.get_raise(api)
                # Detach WAN Edge templates
                reqs = self.detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_not_vsmart),
                                   dryrun=parsed_args.dryrun, log_context='detaching WAN Edges')
                if reqs:
                    self.log_debug('%sDetach requests processed: %s', log_prefix, reqs)
                else:
                    self.log_info('No WAN Edge attached')
                # Deactivate vSmart policy
                if not parsed_args.dryrun:
                    action_list = self.deactivate_policy(api)
                    if len(action_list) == 0:
                        self.log_info('No vSmart policy activated')
                    else:
                        self.wait_actions(api, action_list, 'deactivating vSmart policy', raise_on_failure=True)
                # Detach vSmart template
                reqs = self.detach(api, template_index.filtered_iter(DeviceTemplateIndex.is_vsmart),
                                   dryrun=parsed_args.dryrun, log_context='detaching vSmarts')
                if reqs:
                    self.log_debug('%sDetach requests processed: %s', log_prefix, reqs)
                else:
                    self.log_info('No vSmart attached')
            except (RestAPIException, WaitActionsException) as ex:
                self.log_critical('Detach failed: %s', ex)
                return

        for tag in ordered_tags(parsed_args.tag, parsed_args.tag != CATALOG_TAG_ALL):
            self.log_info('Inspecting %s items', tag)
            regex = parsed_args.regex or parsed_args.not_regex
            matched_item_iter = (
                (item_name, item_id, item_cls, info)
                for _, info, index, item_cls in self.index_iter(api, catalog_iter(tag, version=api.server_version))
                for item_id, item_name in index
                if regex is None or regex_search(regex, item_name, inverse=parsed_args.regex is None)
            )
            for item_name, item_id, item_cls, info in matched_item_iter:
                item = item_cls.get(api, item_id)
                if item is None:
                    self.log_warning('Failed retrieving %s %s', info, item_name)
                    continue
                if item.is_readonly or item.is_system:
                    self.log_debug('Skipped %s %s %s', 'read-only' if item.is_readonly else 'system', info, item_name)
                    continue
                if parsed_args.dryrun:
                    self.log_info('DRY-RUN: Delete %s %s', info, item_name)
                    continue

                if api.delete(item_cls.api_path.delete, item_id):
                    self.log_info('Done: Delete %s %s', info, item_name)
                else:
                    self.log_warning('Failed deleting %s %s', info, item_name)

        return
