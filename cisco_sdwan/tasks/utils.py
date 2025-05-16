"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.tasks.utils
 This module implements task utility classes and functions
"""
import os
import re
import argparse
from datetime import date
from getpass import getpass
from typing import Optional, Dict, List, Set, Union, Type, Any
from collections.abc import Callable, Iterable
from cisco_sdwan.base.catalog import catalog_tags, op_catalog_tags, op_catalog_commands, CATALOG_TAG_ALL, OpType
from cisco_sdwan.tasks.common import Task
from cisco_sdwan.tasks.validators import (validate_workdir, validate_regex, validate_existing_file, validate_zip_file,
                                          validate_ipv4, validate_site_id, validate_ext_template, validate_version,
                                          validate_filename)

# Default local data store
DEFAULT_WORKDIR_FORMAT = 'backup_{address}_{date:%Y%m%d}'


def default_workdir(address: Optional[str]) -> str:
    """
    Generate a default workdir name based on the provided vManage address and current date.
    
    @param address: vManage address to include in the workdir name. If None, 'VMANAGE-ADDRESS' is used.
    @return: Formatted workdir name string
    """
    return DEFAULT_WORKDIR_FORMAT.format(date=date.today(), address=address or 'VMANAGE-ADDRESS')


class TaskOptions:
    """
    Registry for task classes. Provides methods to register, retrieve and list available tasks.
    Tasks are registered using the @TaskOptions.register decorator.
    """
    _task_options: Dict[str, Type[Task]] = {}

    @classmethod
    def task(cls, task_str: str) -> Type[Task]:
        """
        Retrieve a task class by its registered name.
        
        @param task_str: String identifying the task
        @return: Task class if found
        @raises argparse.ArgumentTypeError: If task_str is not a registered task
        """
        task_cls = cls._task_options.get(task_str)
        if task_cls is None:
            raise argparse.ArgumentTypeError(f'Invalid task. Options are: {cls.options()}.')
        return task_cls

    @classmethod
    def options(cls) -> str:
        """
        Return a comma-separated string of all registered task names.
        
        @return: String containing all registered task names
        """
        return ', '.join(cls._task_options)

    @classmethod
    def register(cls, task_name: str) -> Callable[[Type[Task]], Type[Task]]:
        """
        Decorator used for registering tasks.
        The class being decorated needs to be a subclass of Task.
        
        @param task_name: String presented to the user to select a task
        @return: decorator
        """

        def decorator(task_cls: Type[Task]) -> Type[Task]:
            if not isinstance(task_cls, type) or not issubclass(task_cls, Task):
                raise SastreException(f'Invalid task registration attempt: {task_cls.__name__}')

            cls._task_options[task_name] = task_cls
            return task_cls

        return decorator


class TagOptions:
    """
    Provides methods to validate, retrieve, and list available tags.
    """
    tag_options: Set[str] = catalog_tags() | {CATALOG_TAG_ALL}

    @classmethod
    def tag(cls, tag_str: str) -> str:
        """
        Validate a tag string against registered tags.
        
        @param tag_str: Tag string to validate
        @return: The validated tag string
        @raises argparse.ArgumentTypeError: If tag_str is not a valid tag
        """
        if tag_str not in cls.tag_options:
            raise argparse.ArgumentTypeError(f'"{tag_str}" is not a valid tag. Available tags: {cls.options()}.')

        return tag_str

    @classmethod
    def tag_list(cls, tag_str_list: List[str]) -> List[str]:
        """
        Validate a list of tag strings against registered tags.
        
        @param tag_str_list: List of tag strings to validate
        @return: List of validated tag strings
        @raises argparse.ArgumentTypeError: If any tag in tag_str_list is not valid
        """
        return [cls.tag(tag_str) for tag_str in tag_str_list]

    @classmethod
    def options(cls) -> str:
        """
        Return a comma-separated string of all registered tags.
        The special tag 'all' always appears first.
        
        @return: String containing all registered tags
        """
        return ', '.join(sorted(cls.tag_options, key=lambda x: '' if x == CATALOG_TAG_ALL else x))


class OpCmdOptions:
    """
    Provides methods to list available tags and commands for different operation types.
    """
    @classmethod
    def tags(cls, op_type: OpType) -> str:
        """
        Return a comma-separated string of all tags for a specific operation type.
        The special tag 'all' always appears first.
        
        @param op_type: Operation type enum value
        @return: String containing all tags for the specified operation type
        """
        return ', '.join(
            sorted(op_catalog_tags(op_type) | {CATALOG_TAG_ALL}, key=lambda x: '' if x == CATALOG_TAG_ALL else x)
        )

    @classmethod
    def commands(cls, op_type: OpType) -> str:
        """
        Return a comma-separated string of all commands for a specific operation type.
        
        @param op_type: Operation type enum value
        @return: String containing all commands for the specified operation type
        """
        return ', '.join(sorted(op_catalog_commands(op_type)))


class OpCmdSemantics(argparse.Action):
    """
    Base class for operational command semantics validation.
    Validates that command arguments are valid for a specific operation type.
    """
    # Using an action as opposed to a type check so that it can evaluate the full command line passed as opposed to
    # individual tokens.
    op_type: Optional[OpType] = None

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, 
                 values: List[str], option_string: Optional[str] = None) -> None:
        """
        Validate command arguments against available options for the operation type.
        
        @param parser: ArgumentParser instance
        @param namespace: Namespace to store the argument
        @param values: Command arguments to validate
        @param option_string: Option string used to invoke this action
        @raises argparse.ArgumentError: If the command is not valid for this operation type
        """
        full_command = ' '.join(values)
        pass_options = [
            len(values) == 1 and CATALOG_TAG_ALL in values,
            len(values) == 1 and set(values) <= op_catalog_tags(self.op_type),
            full_command in op_catalog_commands(self.op_type)
        ]
        if not any(pass_options):
            raise argparse.ArgumentError(self, f'"{full_command}" is not valid. '
                                               f'Group options: {OpCmdOptions.tags(self.op_type)}. '
                                               f'Command options: {OpCmdOptions.commands(self.op_type)}.')

        setattr(namespace, self.dest, values)


class RTCmdSemantics(OpCmdSemantics):
    """
    Operational command semantics validation for real-time commands.
    """
    op_type: OpType = OpType.RT


class StateCmdSemantics(OpCmdSemantics):
    """
    Operational command semantics validation for state commands.
    """
    op_type: OpType = OpType.STATE


class StatsCmdSemantics(OpCmdSemantics):
    """
    Operational command semantics validation for statistics commands.
    """
    op_type: OpType = OpType.STATS


#
# Validator wrappers to adapt pydantic validators to argparse
#

def regex_type(regex: str) -> str:
    """
    Validate a regular expression string for use with argparse.
    
    @param regex: Regular expression string to validate
    @return: The validated regular expression string
    @raises argparse.ArgumentTypeError: If regex is not a valid regular expression
    """
    try:
        validate_regex(regex)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return regex


def existing_workdir_type(workdir: str, *, skip_validation: bool = False) -> str:
    """
    Validate that a workdir exists for use with argparse.
    
    @param workdir: Directory path to validate
    @param skip_validation: If True, skip validation and return workdir as-is
    @return: The validated workdir path
    @raises argparse.ArgumentTypeError: If workdir does not exist
    """
    if not skip_validation:
        try:
            validate_workdir(workdir)
        except ValueError as ex:
            raise argparse.ArgumentTypeError(ex) from None

    return workdir


def filename_type(filename: str) -> str:
    """
    Validate a filename for use with argparse.
    
    @param filename: Filename to validate
    @return: The validated filename
    @raises argparse.ArgumentTypeError: If filename is not valid
    """
    try:
        validate_filename(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def existing_file_type(filename: str) -> str:
    """
    Validate that a file exists for use with argparse.
    
    @param filename: Filename to validate
    @return: The validated filename
    @raises argparse.ArgumentTypeError: If the file does not exist
    """
    try:
        validate_existing_file(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def zip_file_type(filename: str) -> str:
    """
    Validate that a file exists and is a valid zip archive for use with argparse.
    
    @param filename: Filename to validate
    @return: The validated filename
    @raises argparse.ArgumentTypeError: If the file does not exist or is not a valid zip archive
    """
    try:
        validate_zip_file(filename)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return filename


def ipv4_type(ipv4: str) -> str:
    """
    Validate an IPv4 address string for use with argparse.
    
    @param ipv4: IPv4 address string to validate
    @return: The validated IPv4 address string
    @raises argparse.ArgumentTypeError: If ipv4 is not a valid IPv4 address
    """
    try:
        validate_ipv4(ipv4)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return ipv4


def site_id_type(site_id: str) -> str:
    """
    Validate a site ID string for use with argparse.
    
    @param site_id: Site ID string to validate
    @return: The validated site ID string
    @raises argparse.ArgumentTypeError: If site_id is not a valid site ID
    """
    try:
        validate_site_id(site_id)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return site_id


def ext_template_type(template_str: str) -> str:
    """
    Validate an extended template string for use with argparse.
    
    @param template_str: Extended template string to validate
    @return: The validated extended template string
    @raises argparse.ArgumentTypeError: If template_str is not a valid extended template
    """
    try:
        validate_ext_template(template_str)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return template_str


def version_type(version_str: str) -> str:
    """
    Validate a version string for use with argparse.
    
    @param version_str: Version string to validate
    @return: The cleaned version string
    @raises argparse.ArgumentTypeError: If version_str is not a valid version identifier
    """
    try:
        cleaned_version = validate_version(version_str)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(ex) from None

    return cleaned_version


#
# Argparse specific validators
#

def uuid_type(uuid_str: str) -> str:
    """
    Validate a UUID string for use with argparse.
    
    @param uuid_str: UUID string to validate
    @return: The validated UUID string
    @raises argparse.ArgumentTypeError: If uuid_str is not a valid UUID
    """
    if re.match(r'[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$', uuid_str) is None:
        raise argparse.ArgumentTypeError(f'"{uuid_str}" is not a valid item ID.')

    return uuid_str


def non_empty_type(src_str: str) -> str:
    """
    Validate that a string is not empty for use with argparse.
    
    @param src_str: String to validate
    @return: The validated non-empty string
    @raises argparse.ArgumentTypeError: If src_str is empty after stripping whitespace
    """
    out_str = src_str.strip()
    if len(out_str) == 0:
        raise argparse.ArgumentTypeError('Value cannot be empty.')

    return out_str


def int_type(min_val: int, max_val: int, value_str: str) -> int:
    """
    Validate that an integer is within a specified range for use with argparse.
    
    @param min_val: Minimum allowed value (inclusive)
    @param max_val: Maximum allowed value (inclusive)
    @param value_str: String to convert and validate as an integer
    @return: The validated integer value
    @raises argparse.ArgumentTypeError: If value_str is not a valid integer or is outside the allowed range
    """
    try:
        value_int = int(value_str)
        if not min_val <= value_int <= max_val:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError(f'Invalid value: "{value_str}". Must be an integer between '
                                         f'{min_val} and {max_val}, inclusive.') from None

    return value_int


#
# Miscellaneous cli-input / argparse
#

class TrackedValidator:
    """
    Callable class that wrap a validator function and tracks the number of times the validator is called.
    """
    def __init__(self, validator_fn: Callable[..., Any]):
        """
        Initialize a TrackedValidator.
        
        @param validator_fn: Validator function to track
        """
        self.num_calls: int = 0
        self.validator_fn: Callable[..., Any] = validator_fn

    @property
    def called(self) -> bool:
        """
        Check if the validator has been called at least once.
        
        @return: True if the validator has been called, False otherwise
        """
        return self.num_calls > 0

    def __call__(self, *validator_fn_args: Any) -> Any:
        """
        Call the validator function and increment the call counter.
        
        @param validator_fn_args: Arguments to pass to the validator function
        @return: Result of the validator function
        """
        self.num_calls += 1

        return self.validator_fn(*validator_fn_args)


class ConditionalValidator:
    """
    Callable class that wrap a validator function and conditionally skips validation based on the call count from the
    tracked validator.
    """
    def __init__(self, validator_fn: Callable[..., Any], tracked_validator_obj: TrackedValidator):
        """
        Initialize a ConditionalValidator.
        
        @param validator_fn: Validator function to conditionally call
        @param tracked_validator_obj: TrackedValidator instance to check for previous calls
        """
        self.validator_fn: Callable[..., Any] = validator_fn
        self.tracked_validator_obj: TrackedValidator = tracked_validator_obj

    def __call__(self, *validator_fn_args: Any) -> Any:
        """
        Call the validator function with skip_validation=True if the tracked validator has been called.
        
        @param validator_fn_args: Arguments to pass to the validator function
        @return: Result of the validator function
        """
        return self.validator_fn(*validator_fn_args, skip_validation=self.tracked_validator_obj.called)


class EnvVar(argparse.Action):
    """
    Custom argparse action that supports environment variables as default values.
    """
    def __init__(self, nargs: Optional[str] = None, envvar: Optional[str] = None, 
                 required: bool = True, default: Any = None, **kwargs: Any):
        """
        Initialize an EnvVar action.
        
        @param nargs: Number of arguments (must be None)
        @param envvar: Environment variable name to use for default value
        @param required: Whether the argument is required if no default is found
        @param default: Default value to use if environment variable is not set
        @param kwargs: Additional arguments to pass to the parent class
        @raises ValueError: If nargs is not None or envvar is None
        """
        if nargs is not None:
            raise ValueError('nargs not allowed')
        if envvar is None:
            raise ValueError('envvar is required')

        default = os.environ.get(envvar) or default
        required = required and default is None
        super().__init__(default=default, required=required, **kwargs)

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, 
                 values: Any, option_string: Optional[str] = None) -> None:
        """
        Store the argument value in the namespace.
        
        @param parser: ArgumentParser instance
        @param namespace: Namespace to store the argument
        @param values: Argument value to store
        @param option_string: Option string used to invoke this action
        """
        setattr(namespace, self.dest, values)


class PromptArg:
    """
    Helper class for prompting the user for input with validation.
    """
    def __init__(self, argument: str, prompt: str, secure_prompt: bool = False, 
                 validate: Callable[[str], str] = non_empty_type):
        """
        Initialize a PromptArg.
        
        @param argument: Argument name
        @param prompt: Prompt string to display to the user
        @param secure_prompt: If True, use getpass for secure input (no echo)
        @param validate: Validation function to apply to the input
        """
        self.argument: str = argument
        self.prompt: str = prompt
        self.prompt_func: Callable[[str], str] = getpass if secure_prompt else input
        self.validate: Callable[[str], str] = validate

    def __call__(self) -> str:
        """
        Prompt the user for input, validate it, and return the validated input.
        Retries until valid input is provided or the user terminates with Ctrl+C.
        
        @return: Validated user input
        """
        while True:
            try:
                value = self.validate(self.prompt_func(self.prompt))
            except argparse.ArgumentTypeError as ex:
                print(f'{ex} Please try again, or ^C to terminate.')
            else:
                return value


#
# Exceptions
#

class SastreException(Exception):
    """ Exception for main app errors """
    pass
