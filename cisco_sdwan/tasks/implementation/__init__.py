"""
 Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

 cisco_sdwan.tasks.implementation
 This module contains the implementation of user-facing tasks
"""
from ._backup import TaskBackup
from ._restore import TaskRestore
from ._delete import TaskDelete
from ._migrate import TaskMigrate
from ._attach_detach import TaskAttach, TaskDetach


__all__ = [
    'TaskBackup',
    'TaskRestore',
    'TaskDelete',
    'TaskMigrate',
    'TaskAttach',
    'TaskDetach'
]
