"""Provides the aptly api task states."""
from enum import Enum


class TaskState(Enum):
    """Provides the aptly api task states."""

    INIT = 0
    RUNNING = 1
    SUCCESSFUL = 2
    FAILED = 3
