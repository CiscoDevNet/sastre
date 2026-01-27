import argparse
from typing import Union, Optional
from collections.abc import Callable
from pydantic import field_validator, model_validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_vmanage import EdgeCertificate, EdgeCertificateSync
from cisco_sdwan.tasks.utils import TaskOptions, existing_workdir_type, regex_type, default_workdir
from cisco_sdwan.tasks.common import regex_search, Task, WaitActionsException
from cisco_sdwan.tasks.models import TaskArgs, const
from cisco_sdwan.tasks.validators import validate_regex, validate_workdir


@TaskOptions.register('certificate')
class TaskCertificate(Task):
    SAVINGS_FACTOR = 0.2

    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nCertificate task:')
        task_parser.prog = f'{task_parser.prog} certificate'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='certificate options')
        sub_tasks.required = True

        restore_parser = sub_tasks.add_parser('restore', help='restore certificate status from a backup')
        restore_parser.set_defaults(source_iter=TaskCertificate.restore_iter)
        restore_parser.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                    default=default_workdir(target_address),
                                    help='restore source (default: %(default)s)')

        set_parser = sub_tasks.add_parser('set', help='set certificate status')
        set_parser.set_defaults(source_iter=TaskCertificate.set_iter)
        set_parser.add_argument('status', choices=['invalid', 'staging', 'valid'],
                                help='WAN edge certificate status')

        # Parameters common to all sub-tasks
        for sub_task in (restore_parser, set_parser):
            mutex = sub_task.add_mutually_exclusive_group()
            mutex.add_argument('--regex', metavar='<regex>', type=regex_type,
                               help='regular expression selecting devices to modify certificate status. Matches on '
                                    'the hostname or chassis/uuid. Use "^-$" to match devices without a hostname.')
            mutex.add_argument('--not-regex', metavar='<regex>', type=regex_type,
                               help='regular expression selecting devices NOT to modify certificate status. Matches on '
                                    'the hostname or chassis/uuid.')
            sub_task.add_argument('--dryrun', action='store_true',
                                  help='dry-run mode. List modifications that would be performed without pushing '
                                       'changes to SD-WAN Manager.')

        return task_parser.parse_args(task_args)

    @staticmethod
    def restore_iter(target_certs, parsed_args):
        saved_certs = EdgeCertificate.load(parsed_args.workdir)
        if saved_certs is None:
            raise FileNotFoundError('WAN edge certificates were not found in the backup')

        saved_certs_dict = {uuid: status for uuid, status in saved_certs}

        return (
            (uuid, status, hostname, saved_certs_dict[uuid])
            for uuid, status, hostname, chassis, serial, state in target_certs.extended_iter()
            if uuid in saved_certs_dict
        )

    @staticmethod
    def set_iter(target_certs, parsed_args):
        return (
            (uuid, status, hostname, parsed_args.status)
            for uuid, status, hostname, chassis, serial, state in target_certs.extended_iter()
        )

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.is_dryrun = parsed_args.dryrun
        if parsed_args.source_iter is TaskCertificate.restore_iter:
            start_msg = f'Restore status from workdir: "{parsed_args.workdir}" -> SD-WAN Manager URL: "{api.base_url}"'
        else:
            start_msg = f'Set status to "{parsed_args.status}" -> SD-WAN Manager URL: "{api.base_url}"'
        self.log_info(f'Certificate task: {start_msg}')

        try:
            self.log_info('Loading WAN edge certificate list from target SD-WAN Manager', dryrun=False)
            target_certs = EdgeCertificate.get_raise(api)

            regex = parsed_args.regex or parsed_args.not_regex
            matched_items = (
                (uuid, current_status, hostname, new_status)
                for uuid, current_status, hostname, new_status in parsed_args.source_iter(target_certs, parsed_args)
                if regex is None or regex_search(regex, hostname or '-', uuid, inverse=parsed_args.regex is None)
            )
            update_list = []
            self.log_info('Identifying items to be pushed', dryrun=False)
            for uuid, current_status, hostname, new_status in matched_items:
                if current_status == new_status:
                    self.log_debug(f'Skipping {hostname or uuid}, no changes')
                    continue

                self.log_info(f'Will update {hostname or uuid} status: {current_status} -> {new_status}')
                update_list.append((uuid, new_status))

            if len(update_list) > 0:
                self.log_info('Send certificate status changes to SD-WAN Manager')
                if not self.is_dryrun:
                    api.post(target_certs.status_post_data(*update_list), EdgeCertificate.api_path.post)
                    action_worker = EdgeCertificateSync(api.post({}, EdgeCertificateSync.api_path.post))
                    self.wait_actions(api, [(action_worker, None)], 'certificate sync with controllers',
                                      raise_on_failure=True)
            else:
                self.log_info('No certificate status changes to send')

        except (RestAPIException, FileNotFoundError, WaitActionsException) as ex:
            self.log_critical(f'Failed updating WAN edge certificate status: {ex}')

        return


class CertificateArgs(TaskArgs):
    regex: Optional[str] = None
    not_regex: Optional[str] = None
    dryrun: bool = False

    # Validators
    _validate_regex = field_validator('regex', 'not_regex')(validate_regex)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'CertificateArgs':
        if self.regex is not None and self.not_regex is not None:
            raise ValueError('Argument "not_regex" not allowed with "regex"')

        return self


class CertificateRestoreArgs(CertificateArgs):
    source_iter: const(Callable, TaskCertificate.restore_iter)
    workdir: str

    # Validators
    _validate_workdir = field_validator('workdir')(validate_workdir)


class CertificateSetArgs(CertificateArgs):
    source_iter: const(Callable, TaskCertificate.set_iter)
    status: str

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        status_options = ('invalid', 'staging', 'valid')
        if v not in status_options:
            raise ValueError(f'"{v}" is not a valid certificate status. Options are: {", ".join(status_options)}.')
        return v
