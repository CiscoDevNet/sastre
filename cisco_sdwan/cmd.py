"""
  Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

  cisco_sdwan.cmd
  This module implements the command line top-level parser and task dispatcher
"""
import logging
import logging.config
import logging.handlers
import argparse
import json
import sys
from pathlib import Path
from requests.exceptions import ConnectionError
from .base.rest_api import Rest, LoginFailedException
from .base.catalog import catalog_size, rt_catalog_size
from .base.models_base import ModelException
from .__version__ import __version__ as version
from .__version__ import __doc__ as title
from .tasks.utils import TaskOptions, EnvVar, non_empty_type, PromptArg
from .tasks.implementation import *

# vManage REST API defaults
VMANAGE_PORT = '8443'
REST_TIMEOUT = 300
BASE_URL = 'https://{address}:{port}'

# Default logging configuration - JSON formatted
# Reason for setting level at chardet.charsetprober is to prevent unwanted debug messages from requests module
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


def main():
    # Top-level cli parser
    cli_parser = argparse.ArgumentParser(description=title)
    cli_parser.add_argument('-a', '--address', metavar='<vmanage-ip>', action=EnvVar, required=False,
                            envvar='VMANAGE_IP', type=non_empty_type,
                            help='vManage IP address, can also be defined via VMANAGE_IP environment variable. '
                                 'If neither is provided user is prompted for the address.')
    cli_parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, required=False,
                            envvar='VMANAGE_USER', type=non_empty_type,
                            help='username, can also be defined via VMANAGE_USER environment variable. '
                                 'If neither is provided user is prompted for username.')
    cli_parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, required=False,
                            envvar='VMANAGE_PASSWORD', type=non_empty_type,
                            help='password, can also be defined via VMANAGE_PASSWORD environment variable. '
                                 ' If neither is provided user is prompted for password.')
    cli_parser.add_argument('--port', metavar='<port>', default=VMANAGE_PORT,
                            help='vManage TCP port number (default: %(default)s)')
    cli_parser.add_argument('--timeout', metavar='<timeout>', type=int, default=REST_TIMEOUT,
                            help='REST API timeout (default: %(default)s)')
    cli_parser.add_argument('--verbose', action='store_true',
                            help='increase output verbosity')
    cli_parser.add_argument('--version', action='version',
                            version=f'Sastre Version {version}. Catalog: {catalog_size()} configuration items, '
                                    f'{rt_catalog_size()} realtime items.')
    cli_parser.add_argument('task', metavar='<task>', type=TaskOptions.task,
                            help=f'task to be performed ({TaskOptions.options()})')
    cli_parser.add_argument('task_args', metavar='<arguments>', nargs=argparse.REMAINDER,
                            help='task parameters, if any')
    cli_parser.set_defaults(prompt_arguments=[
        PromptArg('address', 'vManage address: '),
        PromptArg('user', 'vManage user: '),
        PromptArg('password', 'vManage password: ', secure_prompt=True)
    ])
    cli_args = cli_parser.parse_args()

    # Logging setup
    logging_config = json.loads(LOGGING_CONFIG)
    console_handler = logging_config.get('handlers', {}).get('console')
    if cli_args.verbose and console_handler is not None:
        console_handler['level'] = 'INFO'

    file_handler = logging_config.get('handlers', {}).get('file')
    if file_handler is not None:
        Path(file_handler['filename']).parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(logging_config)

    # Dispatch task
    target_address = cli_args.address
    task = cli_args.task()
    parsed_task_args = task.parser(cli_args.task_args, target_address=target_address)
    try:
        if task.is_api_required(parsed_task_args):
            # Evaluate whether user must be prompted for additional arguments
            try:
                for prompt_arg in getattr(cli_args, 'prompt_arguments', []):
                    if getattr(cli_args, prompt_arg.argument) is None:
                        setattr(cli_args, prompt_arg.argument, prompt_arg())
            except KeyboardInterrupt:
                sys.exit(1)

            if target_address != cli_args.address:
                # Target address changed, re-run parser
                parsed_task_args = task.parser(cli_args.task_args, target_address=cli_args.address)

            base_url = BASE_URL.format(address=cli_args.address, port=cli_args.port)
            with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
                # Dispatch to the appropriate task handler
                task.runner(parsed_task_args, api)

        else:
            # Dispatch to the appropriate task handler without api connection
            task.runner(parsed_task_args)

        task.log_info('Task completed %s', task.outcome('successfully', 'with caveats: {tally}'))
    except (LoginFailedException, ConnectionError, FileNotFoundError, ModelException) as ex:
        logging.getLogger(__name__).critical(ex)
