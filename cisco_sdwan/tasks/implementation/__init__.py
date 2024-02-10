"""
 Sastre - Cisco-SDWAN Automation Toolset

 cisco_sdwan.tasks.implementation
 This module contains the implementation of user-facing tasks
"""
from ._backup import TaskBackup, BackupArgs
from ._restore import TaskRestore, RestoreArgs
from ._delete import TaskDelete, DeleteArgs
from ._migrate import TaskMigrate, MigrateArgs
from ._attach_detach import TaskAttach, TaskDetach, AttachVsmartArgs, AttachEdgeArgs, DetachVsmartArgs, DetachEdgeArgs
from ._certificate import TaskCertificate, CertificateSetArgs, CertificateRestoreArgs
from ._transform import (TaskTransform, TransformCopyArgs, TransformRenameArgs, TransformRecipeArgs,
                         TransformBuildArgs)
from ._list import TaskList, ListConfigArgs, ListCertificateArgs, ListTransformArgs
from ._show_template import TaskShowTemplate, ShowTemplateValuesArgs, ShowTemplateRefArgs
from ._report import TaskReport, ReportCreateArgs, ReportDiffArgs
from ._show import (TaskShow, ShowDevicesArgs, ShowRealtimeArgs, ShowStateArgs, ShowStatisticsArgs, ShowEventsArgs,
                    ShowAlarmsArgs)

__all__ = [
    'TaskBackup',
    'TaskRestore',
    'TaskDelete',
    'TaskMigrate',
    'TaskAttach',
    'TaskDetach',
    'TaskCertificate',
    'TaskTransform',
    'TaskList',
    'TaskShowTemplate',
    'TaskReport',
    'TaskShow',
    'ReportCreateArgs',
    'ReportDiffArgs',
    'RestoreArgs',
    'MigrateArgs',
    'CertificateSetArgs',
    'CertificateRestoreArgs',
    'TransformCopyArgs',
    'TransformRenameArgs',
    'TransformRecipeArgs',
    'TransformBuildArgs',
    'ListConfigArgs',
    'ListCertificateArgs',
    'ListTransformArgs',
    'ShowTemplateValuesArgs',
    'ShowTemplateRefArgs',
    'AttachVsmartArgs',
    'AttachEdgeArgs',
    'DetachVsmartArgs',
    'DetachEdgeArgs',
    'BackupArgs',
    'DeleteArgs',
    'ShowDevicesArgs',
    'ShowRealtimeArgs',
    'ShowStateArgs',
    'ShowStatisticsArgs',
    'ShowEventsArgs',
    'ShowAlarmsArgs'
]
