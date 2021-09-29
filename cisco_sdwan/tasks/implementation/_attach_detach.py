import argparse
from functools import partial
from typing import Union, Optional
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_vmanage import DeviceTemplateIndex, EdgeInventory, ControlInventory
from cisco_sdwan.tasks.utils import (TaskOptions, existing_workdir_type, regex_type, default_workdir, ipv4_type,
                                     site_id_type, int_type)
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException, device_iter

# Default number of devices to include per attach/detach request. The value of 200 was adopted because it is what was
# validated in the lab
DEFAULT_BATCH_SIZE = 200


@TaskOptions.register('attach')
class TaskAttach(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nAttach templates task:')
        task_parser.prog = f'{task_parser.prog} attach'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='attach options')
        sub_tasks.required = True

        edge_parser = sub_tasks.add_parser('edge', help='attach templates to WAN edges')
        edge_parser.set_defaults(template_filter=DeviceTemplateIndex.is_not_vsmart,
                                 device_set=TaskAttach.edge_set,
                                 set_title="WAN Edges")

        vsmart_parser = sub_tasks.add_parser('vsmart', help='attach template to vSmarts')
        vsmart_parser.set_defaults(template_filter=DeviceTemplateIndex.is_vsmart,
                                   device_set=TaskAttach.vsmart_set,
                                   set_title="vSmarts")

        # Parameters common to all sub-tasks
        for sub_task in (edge_parser, vsmart_parser):
            sub_task.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                  default=default_workdir(target_address), help='attach source (default: %(default)s)')
            sub_task.add_argument('--templates', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting templates to attach. Match on template name.')
            sub_task.add_argument('--devices', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting devices to attach. Match on device name.')
            sub_task.add_argument('--reachable', action='store_true', help='select reachable devices only')
            sub_task.add_argument('--site', metavar='<id>', type=site_id_type, help='select devices with site ID')
            sub_task.add_argument('--system-ip', metavar='<ipv4>', type=ipv4_type, help='select device with system IP')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. Attach operations are listed but not is pushed to vManage.')
            sub_task.add_argument('--batch', metavar='<size>', type=partial(int_type, 1, 9999),
                                  default=DEFAULT_BATCH_SIZE,
                                  help='maximum number of devices to include per vManage attach request '
                                       '(default: %(default)s)')

        return task_parser.parse_args(task_args)

    @staticmethod
    def edge_set(api: Rest) -> set:
        return {uuid for uuid, _ in EdgeInventory.get_raise(api)}

    @staticmethod
    def vsmart_set(api: Rest) -> set:
        return {uuid for uuid, _ in ControlInventory.get_raise(api).filtered_iter(ControlInventory.is_vsmart)}

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info('Starting attach templates%s: Local workdir: "%s" -> vManage URL: "%s"',
                      ', DRY-RUN mode' if parsed_args.dryrun else '', parsed_args.workdir, api.base_url)
        log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''

        try:
            uuid_set = (
                parsed_args.device_set(api) &
                set(uuid for uuid, _ in device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site,
                                                    parsed_args.system_ip))
            )
            target_templates = {item_name: item_id for item_id, item_name in DeviceTemplateIndex.get_raise(api)}
            saved_template_index = DeviceTemplateIndex.load(parsed_args.workdir, raise_not_found=True)
            matched_templates = (
                (saved_name, saved_id, target_templates.get(saved_name))
                for saved_id, saved_name in saved_template_index.filtered_iter(parsed_args.template_filter)
                if parsed_args.templates is None or regex_search(parsed_args.templates, saved_name)
            )

            attach_data = self.attach_template_data(api, parsed_args.workdir, saved_template_index.need_extended_name,
                                                    matched_templates, target_uuid_set=uuid_set)
            reqs = self.attach(api, *attach_data, chunk_size=parsed_args.batch, dryrun=parsed_args.dryrun,
                               log_context=f"attaching {parsed_args.set_title}")
            if reqs:
                self.log_debug('%sAttach requests processed: %s', log_prefix, reqs)
            else:
                self.log_info('%sNo %s attachments to process', log_prefix, parsed_args.set_title)

        except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
            self.log_critical('%sAttach failed: %s', log_prefix, ex)

        return


@TaskOptions.register('detach')
class TaskDetach(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nDetach templates task:')
        task_parser.prog = f'{task_parser.prog} detach'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='detach options')
        sub_tasks.required = True

        edge_parser = sub_tasks.add_parser('edge', help='detach templates from WAN edges')
        edge_parser.set_defaults(template_filter=DeviceTemplateIndex.is_not_vsmart,
                                 set_title="WAN Edges")

        vsmart_parser = sub_tasks.add_parser('vsmart', help='detach template from vSmarts')
        vsmart_parser.set_defaults(template_filter=DeviceTemplateIndex.is_vsmart,
                                   set_title="vSmarts")

        # Parameters common to all sub-tasks
        for sub_task in (edge_parser, vsmart_parser):
            sub_task.add_argument('--templates', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting templates to detach. Match on template name.')
            sub_task.add_argument('--devices', metavar='<regex>', type=regex_type,
                                  help='regular expression selecting devices to detach. Match on device name.')
            sub_task.add_argument('--reachable', action='store_true', help='select reachable devices only')
            sub_task.add_argument('--site', metavar='<id>', type=site_id_type, help='select devices with site ID')
            sub_task.add_argument('--system-ip', metavar='<ipv4>', type=ipv4_type, help='select device with system IP')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. Attach operations are listed but nothing is pushed to vManage.')
            sub_task.add_argument('--batch', metavar='<size>', type=partial(int_type, 1, 9999),
                                  default=DEFAULT_BATCH_SIZE,
                                  help='maximum number of devices to include per vManage detach request '
                                       '(default: %(default)s)')

        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info('Starting detach templates%s: vManage URL: "%s"',
                      ', DRY-RUN mode' if parsed_args.dryrun else '', api.base_url)
        log_prefix = 'DRY-RUN: ' if parsed_args.dryrun else ''

        try:
            matched_devices = dict(
                device_iter(api, parsed_args.devices, parsed_args.reachable, parsed_args.site, parsed_args.system_ip)
            )
            matched_templates = (
                (t_id, t_name)
                for t_id, t_name in DeviceTemplateIndex.get_raise(api).filtered_iter(parsed_args.template_filter)
                if parsed_args.templates is None or regex_search(parsed_args.templates, t_name)
            )
            reqs = self.detach(api, matched_templates, matched_devices, chunk_size=parsed_args.batch,
                               dryrun=parsed_args.dryrun, log_context=f"detaching {parsed_args.set_title}")
            if reqs:
                self.log_debug('%sDetach requests processed: %s', log_prefix, reqs)
            else:
                self.log_info('%sNo %s detachments to process', log_prefix, parsed_args.set_title)

        except (RestAPIException, WaitActionsException) as ex:
            self.log_critical('Detach failed: %s', ex)

        return
