import socket
import json
import aiohttp

from pathlib import Path
from enum import Enum

from ..logger import logger
from .configuration import Configuration
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


async def trigger_hook(method, url, skip_ssl, body=None):
    """
    Triggers a web hook.

    Args:
        method (str): The http method to be used. E.g. POST
        url (str): The url to send the request to.
        skip_ssl (bool): Set to True if ssl handshake should not be verified.
        body (str): The request body, only pass if method is POST
    """
    data = None
    headers = {"content-type": "application/json"}
    verify = not skip_ssl

    try:
        data = json.loads(body)
    except Exception as exc:
        logger.error("hook: error parsing json body: {}".format(exc))
        return

    connector = aiohttp.TCPConnector(verify_ssl=verify)

    if method.lower() == "post":
        async with aiohttp.ClientSession(connector=connector) as http:
            async with http.post(url, headers=headers, data=json.dumps(data)) as resp:
                if resp.status != 200:
                    logger.warning("trigger web hook '%s' to '%s' returned %d ", method, url, resp.status)

    elif method.lower() == "get":
        async with aiohttp.ClientSession() as http:
            async with http.get(url) as resp:
                if resp.status != 200:
                    logger.warning("trigger web hook '%s' to '%s' returned %d ", method, url, resp.status)

async def notify(subject, event, data):
    await enqueue_notification({"notify": {"subject": subject, "event": event, "data": data}})


async def run_hooks(build_id):
    await enqueue_notification({"hooks": {"build_id": build_id}})
