from enum import Enum

# from ..logger import logger
from .queues import enqueue_notification


class Subject(Enum):
    """Provides the molior subject types"""

    websocket = 1
    eventwatch = 2
    userrole = 3
    user = 4
    project = 5
    projectversion = 6
    build = 7
    buildlog = 8
    mirror = 9
    node = 10


class Event(Enum):
    """Provides the molior event types"""

    added = 1
    changed = 2
    removed = 3
    connected = 4
    done = 5


class Action(Enum):
    """Provides the molior action types"""

    add = 1
    change = 2
    remove = 3
    start = 4
    stop = 5


async def notify(subject, event, data):
    await enqueue_notification({"notify": {"subject": subject, "event": event, "data": data}})
