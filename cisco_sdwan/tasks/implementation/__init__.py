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
from ._transform import TaskTransform, TransformCopyArgs, TransformRenameArgs, TransformRecipeArgs

__all__ = [
    'TaskBackup',
    'TaskRestore',
    'TaskDelete',
    'TaskMigrate',
    'TaskAttach',
    'TaskDetach',
    'TaskTransform',
    'BackupArgs',
    'RestoreArgs',
    'DeleteArgs',
    'MigrateArgs',
    'AttachVsmartArgs',
    'AttachEdgeArgs',
    'DetachVsmartArgs',
    'DetachEdgeArgs',
    'TransformCopyArgs',
    'TransformRenameArgs',
    'TransformRecipeArgs'
]
