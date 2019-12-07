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
from pathlib import Path
from datetime import date
from .base.rest_api import Rest, LoginFailedException
from .base.catalog import catalog_size
from .base.models_base import ModelException
from .__version__ import __version__ as version
from .__version__ import __doc__ as title
from .tasks.utils import TaskOptions, TagOptions, EnvVar
from .tasks.implementation import *

# Default local data store
WORK_DIR = 'backup_{address}_{date:%Y%m%d}'

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
    cli_parser.add_argument('-a', '--address', metavar='<vmanage-ip>', action=EnvVar, envvar='VMANAGE_IP',
                            help='vManage IP address, can also be provided via VMANAGE_IP environment variable')
    cli_parser.add_argument('-u', '--user', metavar='<user>', action=EnvVar, envvar='VMANAGE_USER',
                            help='username, can also be provided via VMANAGE_USER environment variable')
    cli_parser.add_argument('-p', '--password', metavar='<password>', action=EnvVar, envvar='VMANAGE_PASSWORD',
                            help='password, can also be provided via VMANAGE_PASSWORD environment variable')
    cli_parser.add_argument('--port', metavar='<port>', default=VMANAGE_PORT,
                            help='vManage TCP port number (default is {port})'.format(port=VMANAGE_PORT))
    cli_parser.add_argument('--timeout', metavar='<timeout>', type=int, default=REST_TIMEOUT,
                            help='REST API timeout (default is {timeout}s)'.format(timeout=REST_TIMEOUT))
    cli_parser.add_argument('--verbose', action='store_true',
                            help='increase output verbosity')
    cli_parser.add_argument('--version', action='version',
                            version='''Sastre Version {version}. Catalog info: {num} items, tags: {tags}.
                                    '''.format(version=version, num=catalog_size(), tags=TagOptions.options()))
    cli_parser.add_argument('task', metavar='<task>', type=TaskOptions.task,
                            help='task to be performed ({options})'.format(options=TaskOptions.options()))
    cli_parser.add_argument('task_args', metavar='<arguments>', nargs=argparse.REMAINDER,
                            help='task parameters, if any')
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
    base_url = BASE_URL.format(address=cli_args.address, port=cli_args.port)
    default_workdir = WORK_DIR.format(address=cli_args.address, date=date.today())

    parsed_task_args = cli_args.task.parser(default_workdir, cli_args.task_args)
    try:
        with Rest(base_url, cli_args.user, cli_args.password, timeout=cli_args.timeout) as api:
            # Dispatch to the appropriate task handler
            cli_args.task.runner(api, parsed_task_args)
        cli_args.task.log_info('Task completed %s', cli_args.task.outcome('successfully', 'with caveats: {tally}'))
    except (LoginFailedException, FileNotFoundError, ModelException) as ex:
        logging.getLogger(__name__).critical(ex)
