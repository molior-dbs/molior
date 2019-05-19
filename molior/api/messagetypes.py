"""
Provides the molior-web message types.
"""
from enum import Enum


class Subject(Enum):
    """Provides the molior-web subject types"""

    websocket = 1
    eventwatch = 2
    userrole = 3
    user = 4
    project = 5
    projectversion = 6
    build = 7
    livelog = 8


class Event(Enum):
    """Provides the molior-web event types"""

    added = 1
    changed = 2
    removed = 3
    connected = 4


class Action(Enum):
    """Provides the molior-web action types"""

    add = 1
    change = 2
    remove = 3
    start = 4
    stop = 5
