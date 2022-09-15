import json
import re
from pathlib import Path
from zipfile import is_zipfile
from cisco_sdwan.base.models_base import filename_safe, DATA_DIR, ExtendedTemplate


def validate_regex(regex: str) -> str:
    if regex is not None:
        try:
            re.compile(regex)
        except (re.error, TypeError):
            raise ValueError(f'"{regex}" is not a valid regular expression.') from None

    return regex


def validate_workdir(workdir: str) -> str:
    if not Path(DATA_DIR, workdir).exists():
        raise ValueError(f'Work directory "{workdir}" not found.')

    return workdir


def validate_filename(filename: str) -> str:
    """ Validate file name. If filename is a path containing a directory, validate whether it exists.
    """
    file_path = Path(filename)
    if not file_path.parent.exists():
        raise ValueError(f'Directory for "{filename}" does not exist')

    # Also allow . on filename, on top of what's allowed by filename_safe
    if re.sub(r'\.', '_', file_path.name) != filename_safe(file_path.name):
        raise ValueError(
            f'Invalid name "{file_path.name}". Only alphanumeric characters, "-", "_", and "." are allowed.'
        )

    return filename


def validate_existing_file(filename: str) -> str:
    """ Validate whether filename exists
    """
    if not Path(filename).exists():
        raise ValueError(f'File "{filename}" not found.')

    return filename


def validate_zip_file(filename: str) -> str:
    """ Validate whether filename exists and is a valid zip archive
    """
    validate_existing_file(filename)
    if not is_zipfile(filename):
        raise ValueError(f'File "{filename}" is not a valid zip archive.')

    return filename


def validate_ipv4(ipv4_str: str) -> str:
    if re.match(r'\d+(?:\.\d+){3}$', ipv4_str) is None:
        raise ValueError(f'"{ipv4_str}" is not a valid IPv4 address.')

    return ipv4_str


def validate_site_id(site_id: str) -> str:
    try:
        if not 0 <= int(site_id) <= 4294967295:
            raise ValueError()
    except ValueError:
        raise ValueError(f'"{site_id}" is not a valid site-id.') from None

    return site_id


def validate_ext_template(template_str: str) -> str:
    # ExtendedTemplate will raise ValueError on validation failures
    ExtendedTemplate(template_str)('test')

    return template_str


def validate_version(version_str: str) -> str:
    # Development versions may follow this format: '20.1.999-98'
    if re.match(r'\d+([.-]\d+){1,3}$', version_str) is None:
        raise ValueError(f'"{version_str}" is not a valid version identifier.')

    return '.'.join(([str(int(v)) for v in version_str.replace('-', '.').split('.')] + ['0', ])[:2])


def validate_json(json_str: str) -> str:
    try:
        json.loads(json_str)
    except json.JSONDecodeError as ex:
        raise ValueError(f'Invalid JSON data: {ex}') from None

    return json_str
