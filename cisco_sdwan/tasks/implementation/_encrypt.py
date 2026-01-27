import argparse
from getpass import getpass
from typing import Union, Optional
from collections.abc import Callable
from pydantic import field_validator, ValidationError
import yaml
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest, RestAPIException
from cisco_sdwan.base.models_vmanage import EncryptText
from cisco_sdwan.tasks.utils import TaskOptions, existing_file_type
from cisco_sdwan.tasks.common import Task, Table, TaskException
from cisco_sdwan.tasks.models import const, TaskArgs
from ._transform import TransformRecipe, RecipeException, RECIPE_VALUE_CHANGE_ME


class StopInputException(Exception):
    """ Exception indicating need to stop further processing of user input in interactive mode sessions """
    pass


@TaskOptions.register('encrypt')
class TaskEncrypt(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nEncrypt task:')
        task_parser.prog = f'{task_parser.prog} encrypt'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='encrypt options')
        sub_tasks.required = True

        values_parser = sub_tasks.add_parser('values', help='encrypt provided list of clear text values')
        values_parser.set_defaults(subtask_handler=TaskEncrypt.values)
        values_parser.add_argument('values', metavar='<value>', nargs='*',
                                   help='one or more clear text values to be encrypted by SD-WAN Manager. '
                                        'If no value is provided, enter interactive mode.')

        recipe_parser = sub_tasks.add_parser('recipe',
                                             help='interactively encrypt based on recipe (from transform build-recipe)')
        recipe_parser.set_defaults(subtask_handler=TaskEncrypt.recipe)
        recipe_parser.add_argument('recipe_file', metavar='<filename>', type=existing_file_type,
                                   help='recipe YAML file')

        return task_parser.parse_args(task_args)

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        self.log_info(f'Encrypt task: SD-WAN Manager URL: "{api.base_url}"')

        return parsed_args.subtask_handler(self, parsed_args, api)

    def recipe(self, parsed_args, api: Rest) -> Union[None, list]:
        try:
            recipe = TransformRecipe.parse_yaml(parsed_args.recipe_file)
        except (ValidationError, RecipeException) as ex:
            raise TaskException(f'Error loading transform recipe: {ex}') from None

        if not recipe.crypt_updates:
            self.log_warning(f"Recipe '{parsed_args.recipe_file}' does not contain crypt_updates")
            return

        update_list = [(resource, replace) for resource in recipe.crypt_updates for replace in resource.replacements
                       if replace.to_value == RECIPE_VALUE_CHANGE_ME]
        if not update_list:
            self.log_warning(f"Recipe '{parsed_args.recipe_file}' has no entries to update")
            return

        print(f'Interactive update of recipe file "{parsed_args.recipe_file}", '
              'press <ENTER> on empty value or ^C to abort without saving.\n')
        try:
            for resource, replace in update_list:
                print(f'Resource {resource.resource_name}, from_value: {replace.from_value}')
                if not (input_value := getpass('Value to encrypt: ')):
                    raise StopInputException()

                if (encrypted_value := self.encrypt_text(input_value, api)) is not None:
                    print(f'Encrypted to_value: {encrypted_value}\n')
                    replace.to_value = encrypted_value

        except (KeyboardInterrupt, StopInputException):
            print('')
            self.log_warning('Interrupted by user, recipe file was not updated')
        else:
            with open(parsed_args.recipe_file, 'w') as file:
                yaml.dump(
                    recipe.model_dump(exclude_none=True, exclude_defaults=True), sort_keys=False, indent=2, stream=file
                )
            self.log_info(f'Recipe file "{parsed_args.recipe_file}" updated')

        return

    def values(self, parsed_args, api: Rest) -> Union[None, list]:
        # Interactive mode
        if not parsed_args.values:
            print('Interactive mode, press <ENTER> on empty value or ^C to quit.')
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
    # Only have TaskEncrypt.values subtask because interactive mode should not be called programmatically
    subtask_handler: const(Callable, TaskEncrypt.values)
    values: list[str]

    # Validators
    @field_validator('values')
    @classmethod
    def validate_cmd(cls, values: list[str]) -> list[str]:
        # Zero length values indicate interactive mode, which is not allowed when encrypt is called programmatically
        if len(values) == 0:
            raise ValueError("Values must not be empty")

        return values
