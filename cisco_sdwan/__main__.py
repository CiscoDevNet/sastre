"""
  Sastre - Cisco-SDWAN Automation Toolset

  cisco_sdwan.__main__
  This module implements the command line top-level parser and task dispatcher
"""
import logging
import logging.config
import logging.handlers
import argparse
import json
import sys
from pathlib import Path
from requests.exceptions import ConnectionError, HTTPError
from .base.rest_api import Rest, RestAPIException
from .base.catalog import catalog_size, op_catalog_size
from .base.models_base import ModelException, SASTRE_ROOT_DIR
from .__version__ import __version__ as version
from .__version__ import __doc__ as title
from .tasks.utils import TaskOptions, EnvVar, non_empty_type, PromptArg
from .tasks.common import Task, TaskException
from .tasks import implementation

# SDWAN Manager REST API defaults
VMANAGE_PORT = '443'
REST_TIMEOUT = 300

# Default logging configuration - JSON formatted
# Setting level at chardet.charsetprober to prevent unwanted debug messages from requests module
LOGGING_CONFIG = '''
{
    "version": 1,
    "formatters": {
        "simple": {
            "format": "%(levelname)s: %(message)s"
        },
        "detailed": {
            "format": "%(asctime)s: %(name)s: %(levelname)s: %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "WARN",
            "formatter": "simple"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/sastre.log",
            "backupCount": 3,
            "maxBytes": 204800,
            "level": "DEBUG",
            "formatter": "detailed"
        }
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG"
    },
    "loggers": {
        "chardet.charsetprober": {
            "level": "INFO"
        }
    }
}
'''


def setup_logging(logging_config: str, is_verbose: bool = False, is_debug: bool = False) -> None:
    logging_config_dict = json.loads(logging_config)
    console_handler = logging_config_dict.get('handlers', {}).get('console')
    if is_verbose and console_handler is not None:
        console_handler['level'] = 'INFO'
    if is_debug:
        logging_config_dict.setdefault('loggers', {}).setdefault('urllib3.connectionpool', {})['level'] = 'DEBUG'

    file_handler = logging_config_dict.get('handlers', {}).get('file')
    if file_handler is not None:
        file_handler['filename'] = str(Path(SASTRE_ROOT_DIR, file_handler['filename']))
        Path(file_handler['filename']).parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(logging_config_dict)


def execute_task(task_obj: Task, parsed_task_args, is_api_task: bool, base_url: str,
                 user: str | None, password: str | None, apikey: str | None, tenant: str | None,
                 timeout: int, is_verbose: bool) -> None:
    try:
        if is_api_task:
            with Rest(base_url, user, password, apikey=apikey, tenant_name=tenant, timeout=timeout) as api:
                # Dispatch to the appropriate task handler
                task_output = task_obj.runner(parsed_task_args, api)
        else:
            # Dispatch to the appropriate task handler without api connection
            task_output = task_obj.runner(parsed_task_args)

        # Display task output
        if task_output:
            print('\n\n'.join(str(entry) for entry in task_output))

        # Display dryrun report if console logging is disabled (i.e. not in verbose mode)
        if not is_verbose and task_obj.is_dryrun:
            print(str(task_obj.dryrun_report))

        task_obj.log_info(f'Task completed {task_obj.outcome("successfully", "with caveats: {tally}")}')
    except (RestAPIException, ConnectionError, HTTPError, FileNotFoundError, ModelException, TaskException) as ex:
        logging.getLogger(__name__).critical(ex)
    except KeyboardInterrupt:
        logging.getLogger(__name__).critical('Interrupted by user')


def main():
    # Top-level cli parser
    cli_parser = argparse.ArgumentParser(description=title)
    cli_parser.add_argument('-a', '--address', metavar='<manager-ip>', action=EnvVar, required=False,
                            envvar='VMANAGE_IP', type=non_empty_type,
                            help='SD-WAN Manager IP address, can also be defined via VMANAGE_IP environment variable. '
                                 'If neither is provided user is prompted for the address.')
    cli_parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, required=False,
                            envvar='VMANAGE_USER', type=non_empty_type,
                            help='username, can also be defined via VMANAGE_USER environment variable. '
                                 'If neither is provided user is prompted for username.')
    cli_parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, required=False,
                            envvar='VMANAGE_PASSWORD', type=non_empty_type,
                            help='password, can also be defined via VMANAGE_PASSWORD environment variable. '
                                 ' If neither is provided user is prompted for password.')
    cli_parser.add_argument('--apikey', metavar='<api-key>', action=EnvVar, required=False,
                            envvar='VMANAGE_APIKEY', type=non_empty_type,
                            help='SD-WAN Manager API key, can also be defined via VMANAGE_APIKEY environment variable.')
    cli_parser.add_argument('--tenant', metavar='<tenant>', type=non_empty_type,
                            help='tenant name, when using provider accounts in multi-tenant deployments.')
    cli_parser.add_argument('--port', metavar='<port>', default=VMANAGE_PORT, action=EnvVar, envvar='VMANAGE_PORT',
                            help='port number, can also be defined via VMANAGE_PORT environment variable'
                                 ' (default: %(default)s)')
    cli_parser.add_argument('--timeout', metavar='<timeout>', type=int, default=REST_TIMEOUT,
                            help='REST API timeout (default: %(default)ss)')
    cli_parser.add_argument('--verbose', action='store_true',
                            help='increase output verbosity')
    cli_parser.add_argument('--debug', action='store_true',
                            help='include additional API call details to the log files')
    cli_parser.add_argument('--version', action='version',
                            version=f'Sastre Version {version}. Catalog: {catalog_size()} configuration items, '
                                    f'{op_catalog_size()} operational items.')
    cli_parser.add_argument('task', metavar='<task>', type=TaskOptions.task,
                            help=f'task to be performed ({TaskOptions.options()})')
    cli_parser.add_argument('task_args', metavar='<arguments>', nargs=argparse.REMAINDER,
                            help='task parameters, if any')
    cli_args = cli_parser.parse_args()

    setup_logging(LOGGING_CONFIG, cli_args.verbose, cli_args.debug)

    # Prepare task
    task = cli_args.task()
    target_address = cli_args.address
    parsed_task_args = task.parser(cli_args.task_args, target_address=target_address)
    is_api_required = task.is_api_required(parsed_task_args)

    # Evaluate whether user must be prompted for additional arguments
    prompt_args_list: list[PromptArg] = []
    if is_api_required:
        prompt_args_list.append(
            PromptArg('address', 'SD-WAN Manager address: ')
        )
        if cli_args.apikey is None:
            prompt_args_list.extend([
                PromptArg('user', 'SD-WAN Manager user: '),
                PromptArg('password', 'SD-WAN Manager password: ', secure_prompt=True)
            ])
    try:
        for prompt_arg in prompt_args_list:
            if getattr(cli_args, prompt_arg.argument) is None:
                setattr(cli_args, prompt_arg.argument, prompt_arg())
    except KeyboardInterrupt:
        sys.exit(1)

    # Re-run task parser if target address changed
    if is_api_required and target_address != cli_args.address:
        parsed_task_args = task.parser(cli_args.task_args, target_address=cli_args.address)

    execute_task(task_obj=task,
                 parsed_task_args=parsed_task_args,
                 is_api_task=is_api_required,
                 base_url=f'https://{cli_args.address}{"" if cli_args.port == "443" else f":{cli_args.port}"}',
                 user=cli_args.user,
                 password=cli_args.password,
                 apikey=cli_args.apikey,
                 tenant=cli_args.tenant,
                 timeout=cli_args.timeout,
                 is_verbose=cli_args.verbose)


if __name__ == '__main__':
    main()
