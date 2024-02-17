import argparse
from getpass import getpass
from typing import Union, Optional, List
from pydantic import field_validator
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_vmanage import EncryptText
from cisco_sdwan.tasks.utils import TaskOptions
from cisco_sdwan.tasks.common import Task, Table
from cisco_sdwan.tasks.models import TaskArgs


@TaskOptions.register('encrypt')
class TaskEncrypt(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nEncrypt task:')
        task_parser.prog = f'{task_parser.prog} encrypt'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        task_parser.add_argument('values', metavar='<value>', nargs='*',
                                 help='zero or more clear text values to be encrypted by the target vManage')
        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info(f'Encrypt task: vManage URL: "{api.base_url}"')

        # Interactive mode
        if not parsed_args.values:
            print('Interactive mode, press <ENTER> or ^C to quit.')
            while True:
                try:
                    input_value = getpass('Value to encrypt: ')
                except KeyboardInterrupt:
                    print('')
                    input_value = None

                if not input_value:
                    break

                if (encrypted_value := self.encrypt_text(input_value, api)) is not None:
                    print(encrypted_value)

            return

        # Batch mode
        table = Table('Input Value', 'Encrypted Value')
        for input_value in parsed_args.values:
            encrypted_value = self.encrypt_text(input_value, api)
            if encrypted_value is None:
                continue

            table.add(input_value, encrypted_value)

        result_tables = []
        if table:
            result_tables.append(table)

        return result_tables

    def encrypt_text(self, input_value: str, api: Rest) -> Union[None, str]:
        try:
            result = EncryptText(api.post(EncryptText.api_params(input_value), EncryptText.api_path.post))
        except RestAPIException as ex:
            self.log_error(f"Failed retrieving encrypted password for '{input_value}': {ex}")
            return None

        if not result.encrypted_value:
            self.log_error(f"No encrypted value returned for '{input_value}'")
            return None

        return result.encrypted_value


class EncryptArgs(TaskArgs):
    values: List[str]

    # Validators
    @field_validator('values')
    @classmethod
    def validate_cmd(cls, values: List[str]) -> List[str]:
        # Zero length values indicate interactive mode, which is not allowed when encrypt is called programmatically
        if len(values) == 0:
            raise ValueError("Values must not be empty")

        return values
