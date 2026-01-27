import argparse
import json
import re
import yaml
from datetime import date
from difflib import unified_diff, HtmlDiff
from typing import Union, Optional, Any, NamedTuple, Annotated
from collections.abc import Iterator, Callable
from pydantic import field_validator, model_validator, BaseModel, ValidationError, Field, ConfigDict
from cisco_sdwan.__version__ import __doc__ as title
from cisco_sdwan.base.rest_api import Rest
from cisco_sdwan.base.catalog import CATALOG_TAG_ALL, ordered_tags
from cisco_sdwan.tasks.utils import TaskOptions, existing_workdir_type, filename_type, existing_file_type
from cisco_sdwan.tasks.common import Task, Table, TaskException
from cisco_sdwan.tasks.models import TaskArgs, const
from cisco_sdwan.tasks.validators import validate_existing_file, validate_filename, validate_workdir, validate_json
from ._list import TaskList, ListConfigArgs, ListCertificateArgs
from ._show_template import TaskShowTemplate, ShowTemplateValuesArgs, ShowTemplateRefArgs
from ._show import TaskShow, ShowDevicesArgs, ShowRealtimeArgs, ShowStateArgs, ShowStatisticsArgs


# Models for the report specification
class SectionModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    task: str
    args: Optional[dict[str, Any]] = None
    inherit_globals: bool = True
    skip_diff: bool = False

    @field_validator('task')
    @classmethod
    def validate_task(cls, v: str) -> str:
        if tuple(v.split()) not in section_catalog:
            raise ValueError(f"'{v}' is not a valid section task")
        return v

    @property
    def task_label(self) -> tuple[str, ...]:
        return tuple(self.task.split())


class ReportContentModel(BaseModel):
    metadata: Optional[dict] = None
    globals: Optional[dict[str, Any]] = None
    sections: list[SectionModel]

    @property
    def skip_section_set(self) -> set[str]:
        return {section.name for section in self.sections if section.skip_diff}


# Report specification used as default if user did not provide a custom one
DEFAULT_SECTIONS_1: list[dict[str, Any]] = [
    {'name': f'List configuration {tag}', 'task': 'list configuration', 'args': {'tags': [tag]}}
    for tag in ordered_tags(CATALOG_TAG_ALL)
]
DEFAULT_CONTENT_SPEC = {
    'sections': DEFAULT_SECTIONS_1 + [
        {'name': 'List certificate', 'task': 'list certificate'},
        {'name': 'Show-template values', 'task': 'show-template values'},
        {'name': 'Show-template references', 'task': 'show-template references'},
        {'name': 'Show devices', 'task': 'show devices'},
        {'name': 'Show state', 'task': 'show state', 'args': {'cmd': ['all']}},
    ]
}


# Metadata about tasks that can be included in a report
class TaskMeta(NamedTuple):
    task_cls: type[Task]
    task_args_cls: type[TaskArgs]


section_catalog: dict[tuple[str, ...], TaskMeta] = {
    ('show', 'devices'): TaskMeta(TaskShow, ShowDevicesArgs),
    ('show', 'realtime'): TaskMeta(TaskShow, ShowRealtimeArgs),
    ('show', 'state'): TaskMeta(TaskShow, ShowStateArgs),
    ('show', 'statistics'): TaskMeta(TaskShow, ShowStatisticsArgs),
    ('list', 'certificate'): TaskMeta(TaskList, ListCertificateArgs),
    ('list', 'configuration'): TaskMeta(TaskList, ListConfigArgs),
    ('show-template', 'values'): TaskMeta(TaskShowTemplate, ShowTemplateValuesArgs),
    ('show-template', 'references'): TaskMeta(TaskShowTemplate, ShowTemplateRefArgs)
}


def load_content_spec(spec_file: Optional[str], spec_json: Optional[str],
                      spec_default: Optional[dict] = None) -> ReportContentModel:
    def load_yaml(filename):
        try:
            with open(filename) as yaml_file:
                return yaml.safe_load(yaml_file)
        except FileNotFoundError as ex:
            raise FileNotFoundError(f'Could not load report specification file: {ex}') from None
        except yaml.YAMLError as ex:
            raise TaskException(f'Report specification YAML syntax error: {ex}') from None

    def load_json(json_str):
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as ex:
            raise TaskException(f'Report specification JSON syntax error: {ex}') from None

    if spec_file:
        content_spec_dict = load_yaml(spec_file)
    elif spec_json:
        content_spec_dict = load_json(spec_json)
    else:
        content_spec_dict = spec_default

    try:
        return ReportContentModel(**content_spec_dict)
    except ValidationError as e:
        raise TaskException(f'Invalid report specification: {e}') from None


class Report:
    DEFAULT_SUBSECTION_NAME = "Default"

    def __init__(self, filename: str, section_dict: Optional[dict] = None, metadata: Optional[dict] = None) -> None:
        # Report section_dict is {<section_name>: {<subsection_name>: [<subsection lines]}}
        self.section_dict = {} if section_dict is None else section_dict
        self.filename = filename
        self.section_json = []
        self.metadata = metadata

    def add_section(self, section_name: str, subsection_list: list) -> None:
        self.section_json.extend(json.loads(subsection.json()) for subsection in subsection_list)
        for subsection in subsection_list:
            if isinstance(subsection, Table):
                subsection_name = subsection.name or Report.DEFAULT_SUBSECTION_NAME
                subsection_lines = list(subsection.pretty_iter())
            else:
                subsection_name = Report.DEFAULT_SUBSECTION_NAME
                subsection_lines = [str(subsection)]

            self.section_dict.setdefault(section_name, {}).setdefault(subsection_name, []).extend(subsection_lines)

    def render(self) -> Iterator[str]:
        for section_num, (section_name, subsection_dict) in enumerate(self.section_dict.items()):
            if section_num != 0:
                yield ''

            yield f"### {section_name} ###"
            for subsection in subsection_dict.values():
                yield ''
                yield from subsection
            yield ''

    def __str__(self) -> str:
        return '\n'.join(self.render())

    def save(self) -> None:
        with open(self.filename, 'w') as f:
            f.write(str(self))

    @classmethod
    def load(cls, filename: str):
        try:
            with open(filename) as report_f:
                report_data = report_f.read()
        except FileNotFoundError as ex:
            raise FileNotFoundError(f"Failed to load report file: {ex}") from None

        p_section_name = re.compile(r"###(?P<section_name>[^#]+)###$")
        p_subsection_name = re.compile(r"\*{3}(?P<subsection_name>[^*]+)\*{3}$")

        section_dict = {}
        section_name, subsection_name = None, None
        for line in report_data.splitlines():
            if not line.strip():
                continue

            m_section_name = p_section_name.match(line)
            if m_section_name:
                section_name = m_section_name.group('section_name').strip()
                subsection_name = Report.DEFAULT_SUBSECTION_NAME
                continue

            if section_name is None or subsection_name is None:
                continue

            m_subsection_name = p_subsection_name.match(line)
            if m_subsection_name:
                subsection_name = m_subsection_name.group('subsection_name').strip()

            section_dict.setdefault(section_name, {}).setdefault(subsection_name, []).append(line)

        return cls(filename, section_dict)

    def trimmed(self, trim_section_names: set):
        trimmed_section_dict = {
            section_name: section for section_name, section in self.section_dict.items()
            if section_name not in trim_section_names
        }
        return Report(self.filename, trimmed_section_dict)

    def save_json(self, filename: str) -> None:
        report_json = {"metadata": self.metadata, "data": self.section_json}
        with open(filename, "w") as target_f:
            target_f.write(json.dumps(report_json, indent=4))


@TaskOptions.register('report')
class TaskReport(Task):
    @staticmethod
    def parser(task_args, target_address=None):
        task_parser = argparse.ArgumentParser(description=f'{title}\nReport task:')
        task_parser.prog = f'{task_parser.prog} report'
        task_parser.formatter_class = argparse.RawDescriptionHelpFormatter

        sub_tasks = task_parser.add_subparsers(title='report options')
        sub_tasks.required = True

        create_parser = sub_tasks.add_parser('create', help='create a report')
        create_parser.set_defaults(subtask_handler=TaskReport.subtask_create)
        create_parser.add_argument('--file', metavar='<filename>', type=filename_type,
                                   default=f'report_{date.today():%Y%m%d}.txt',
                                   help='report filename (default: %(default)s)')
        create_parser.add_argument('--workdir', metavar='<directory>', type=existing_workdir_type,
                                   help='report from the specified directory instead of target vManage')
        create_parser.add_argument('--diff', metavar='<filename>', type=existing_file_type,
                                   help='generate diff between the specified previous report and the current report')
        create_parser.add_argument('--save-json', metavar='<filename>', type=filename_type,
                                   help='export report as JSON-formatted file')
        diff_parser = sub_tasks.add_parser('diff', help='generate diff between two reports')
        diff_parser.set_defaults(subtask_handler=TaskReport.subtask_diff)
        diff_parser.add_argument('report_a', metavar='<report a>', type=existing_file_type,
                                 help='report a filename (from)')
        diff_parser.add_argument('report_b', metavar='<report b>', type=existing_file_type,
                                 help='report b filename (to)')
        diff_parser.add_argument('--save-html', metavar='<filename>', type=filename_type,
                                 help='save report diff as html file')
        diff_parser.add_argument('--save-txt', metavar='<filename>', type=filename_type,
                                 help='save report diff as text file')

        for sub_task in (create_parser, diff_parser):
            mutex = sub_task.add_mutually_exclusive_group()
            mutex.add_argument('--spec-file', metavar='<filename>', type=existing_file_type,
                               help='load custom report specification from YAML file')
            mutex.add_argument('--spec-json', metavar='<json>',
                               help='load custom report specification from JSON-formatted string')

        return task_parser.parse_args(task_args)

    @staticmethod
    def is_api_required(parsed_args) -> bool:
        return parsed_args.subtask_handler is TaskReport.subtask_create and parsed_args.workdir is None

    def runner(self, parsed_args, api: Optional[Rest] = None) -> Union[None, list]:
        return parsed_args.subtask_handler(self, parsed_args, api)

    def subtask_create(self, parsed_args, api: Optional[Rest]) -> Union[None, list]:
        source_info = f'Local workdir: "{parsed_args.workdir}"' if api is None else f'vManage URL: "{api.base_url}"'
        self.log_info(f'Report create task: {source_info} -> "{parsed_args.file}"')

        self.log_info("Loading report specification")
        content_spec = load_content_spec(parsed_args.spec_file, parsed_args.spec_json, DEFAULT_CONTENT_SPEC)

        report = Report(parsed_args.file, metadata=content_spec.metadata)
        for description, task_cls, task_args in self.section_iter(content_spec, api is not None, parsed_args.workdir):
            try:
                task_output = task_cls().runner(task_args, api)
                if task_output:
                    report.add_section(description, task_output)
            except (TaskException, FileNotFoundError) as ex:
                self.log_error(f'Task {task_cls.__name__} error: {ex}')

        result = None
        if parsed_args.diff:
            self.log_info(f'Starting diff from "{parsed_args.diff}" to "{parsed_args.file}"')
            previous_report = Report.load(parsed_args.diff)
            self.log_info(f'Loaded previous report "{parsed_args.diff}"')
            skip_sections = content_spec.skip_section_set
            result = [diff_txt(previous_report.trimmed(skip_sections), report.trimmed(skip_sections))]
            self.log_info('Completed diff')

        # Saving current report after running the diff in case the previous report had the same filename
        report.save()
        self.log_info(f'Report saved as "{parsed_args.file}"')
        if parsed_args.save_json:
            report.save_json(parsed_args.save_json)
            self.log_info(f'JSON-formatted report saved as "{parsed_args.save_json}"')

        return result

    # noinspection PyUnusedLocal
    def subtask_diff(self, parsed_args, api: Optional[Rest]) -> Union[None, list]:
        self.log_info(f'Report diff task: "{parsed_args.report_a}" <-> "{parsed_args.report_b}"')
        report_a = Report.load(parsed_args.report_a)
        self.log_info(f'Loaded report "{parsed_args.report_a}"')
        report_b = Report.load(parsed_args.report_b)
        self.log_info(f'Loaded report "{parsed_args.report_b}"')

        if parsed_args.spec_file or parsed_args.spec_json:
            self.log_info("Loading report specification, trimming sections with skip_diff set")
            skip_sections = load_content_spec(parsed_args.spec_file, parsed_args.spec_json).skip_section_set
            report_a = report_a.trimmed(skip_sections)
            report_b = report_b.trimmed(skip_sections)

        result = None
        if parsed_args.save_html:
            with open(parsed_args.save_html, 'w') as f:
                f.write(diff_html(report_a, report_b))
            self.log_info(f'HTML report diff saved as "{parsed_args.save_html}"')

        if parsed_args.save_txt:
            with open(parsed_args.save_txt, 'w') as f:
                f.write(diff_txt(report_a, report_b))
            self.log_info(f'Text report diff saved as "{parsed_args.save_txt}"')

        if not parsed_args.save_html and not parsed_args.save_txt:
            result = [diff_txt(report_a, report_b)]

        return result

    def section_iter(self, report_spec: ReportContentModel,
                     has_api_session: bool,
                     workdir: Optional[str]) -> Iterator[tuple[str, type[Task], TaskArgs]]:
        """
        An iterator over the different sections of the report, including task and arguments for the task.
        @param report_spec: report specification to use for generating this report
        @param has_api_session: whether the report is running with a vManage session or offline (i.e. off a backup)
        @param workdir: workdir value, if provided to the report task.
        @return: an iterator of (<description>, <task class>, <task args>)
        """
        spec_global_args = report_spec.globals or {}

        for section_num, section in enumerate(report_spec.sections):
            task_meta: TaskMeta = section_catalog[section.task_label]

            # Resolving task args: section args have higher precedence over global args
            # Trim global args to only the ones relevant to the task, then merge with section args
            spec_section_args = section.args or {}
            if section.inherit_globals:
                imported_global_args = {
                    k: v for k, v in spec_global_args.items() if k in task_meta.task_args_cls.model_fields
                }
                spec_args = {**imported_global_args, **spec_section_args}
            else:
                spec_args = spec_section_args

            # Parse task args
            try:
                task_args = task_meta.task_args_cls(**spec_args)
            except ValidationError as ex:
                self.log_error(f"Invalid report specification: {section.name} (sections -> {section_num}): {ex}")
                continue

            if workdir is not None and hasattr(task_args, 'workdir') and task_args.workdir is None:
                task_args.workdir = workdir

            if task_meta.task_cls.is_api_required(task_args) and not has_api_session:
                # Skip report sections that require an api session when report is run offline, i.e. from a workdir
                self.log_debug(f"Skipping: {section.name} (sections -> {section_num}): report from workdir")
                continue

            yield section.name, task_meta.task_cls, task_args


def diff_html(a: Report, b: Report) -> str:
    diff = HtmlDiff()
    return diff.make_file(list(a.render()), list(b.render()), fromdesc=a.filename, todesc=b.filename, context=False)


def diff_txt(a: Report, b: Report) -> str:
    return '\n'.join(diff_txt_iter(a, b))


def diff_txt_iter(a: Report, b: Report) -> Iterator[str]:
    def spaced_line(line: str) -> Iterator[str]:
        yield ""
        yield line

    def subsection_lines(subsection_iter: Iterator[str]) -> list[str]:
        lines = []
        for subsection in subsection_iter:
            lines.extend(subsection.splitlines())
        return lines

    yield from spaced_line(f"### Report Diff - a/{a.filename} <-> b/{b.filename} ###")

    # Find sections that were on <a> but not on <b>
    for a_section_name in set(a.section_dict) - set(b.section_dict):
        yield from spaced_line(f"deleted a/{a_section_name.lower()}")

    # Diff each section
    for section_name, b_subsection_dict in b.section_dict.items():
        a_subsection_dict = a.section_dict.get(section_name)
        if a_subsection_dict is None:
            yield from spaced_line(f"new b/{section_name.lower()}")
            continue

        # Find subsections that were on <a> but not on <b>
        for a_subsection_name in set(a_subsection_dict) - set(b_subsection_dict):
            yield from spaced_line(f"deleted a/{a_subsection_name.lower()}")

        # Diff each subsection
        for subsection_name, b_subsections in b_subsection_dict.items():
            a_subsections = a_subsection_dict.get(subsection_name)
            if a_subsections is None:
                yield from spaced_line(f"new b/{subsection_name.lower()}")
                continue

            diff_info = [section_name.lower()]
            if subsection_name != Report.DEFAULT_SUBSECTION_NAME:
                diff_info.append(subsection_name.lower())

            is_first = True
            for diff_line in unified_diff(subsection_lines(a_subsections), subsection_lines(b_subsections),
                                          fromfile=f"a/{a.filename}", tofile=f"b/{b.filename}", lineterm='', n=1):
                if is_first:
                    yield from spaced_line(f"changed {', '.join(diff_info)}")
                    is_first = False

                yield diff_line

    yield from spaced_line("### End Report Diff ###")
    yield ""


class ReportCreateArgs(TaskArgs):
    subtask_handler: const(Callable, TaskReport.subtask_create)
    file: Annotated[str, Field(validate_default=True)] = None
    workdir: Optional[str] = None
    diff: Optional[str] = None
    save_json: Optional[str] = None
    spec_file: Optional[str] = None
    spec_json: Optional[str] = None

    # Validators
    _validate_workdir = field_validator('workdir')(validate_workdir)
    _validate_existing_file = field_validator('spec_file', 'diff')(validate_existing_file)
    _validate_json = field_validator('spec_json')(validate_json)
    _validate_filename = field_validator('save_json')(validate_filename)

    @field_validator('file', mode='before')
    @classmethod
    def validate_report_file(cls, v):
        filename = (isinstance(v, str) and v) or f'report_{date.today():%Y%m%d}.txt'
        return validate_filename(filename)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'ReportCreateArgs':
        if self.spec_file is not None and self.spec_json is not None:
            raise ValueError('Argument "spec_file" not allowed with "spec_json"')

        return self


class ReportDiffArgs(TaskArgs):
    subtask_handler: const(Callable, TaskReport.subtask_diff)
    report_a: Optional[str] = None
    report_b: Optional[str] = None
    save_html: Optional[str] = None
    save_txt: Optional[str] = None
    spec_file: Optional[str] = None
    spec_json: Optional[str] = None

    # Validators
    _validate_existing_file = field_validator('report_a', 'report_b', 'spec_file')(validate_existing_file)
    _validate_json = field_validator('spec_json')(validate_json)
    _validate_filename = field_validator('save_html', 'save_txt')(validate_filename)

    @model_validator(mode='after')
    def mutex_validations(self) -> 'ReportDiffArgs':
        if self.spec_file is not None and self.spec_json is not None:
            raise ValueError('Argument "spec_file" not allowed with "spec_json"')

        return self
