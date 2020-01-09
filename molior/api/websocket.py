"""
Provides the moliorweb websocket message handler.
"""

import logging
import asyncio
import json
from pathlib import Path

from .app import app
from .messagetypes import Subject, Event, Action
from .livelogger import LiveLogger

BUILD_OUT_PATH = Path("/var/lib/molior/buildout")
logger = logging.getLogger("molior")  # pylint: disable=invalid-name


async def start_livelogger(websocket, data):
    """
    Starts the livelogger for the given
    websocket client.

    Args:
        websocket: The websocket instance.
        data (dict): The received data.
    """
    if "build_id" not in data:
        return False

    path = BUILD_OUT_PATH / str(data.get("build_id")) / "build.log"
    llogger = LiveLogger(websocket.send_str, path)

    if hasattr(websocket, "logger") and websocket.logger:
        await stop_livelogger(websocket, data)

    websocket.logger = llogger
    loop = asyncio.get_event_loop()
    loop.create_task(llogger.start())
    logger.debug("new logger task created for '%s'", str(path))


async def stop_livelogger(websocket, _):
    """
    Stops the livelogger.
    """
    if hasattr(websocket, "logger") and websocket.logger:
        await websocket.logger.stop()


async def dispatch(websocket, message):
    """
    Dispatchers websocket requests to different
    handler functions.

    Args:
        websocket: The websocket instance.
        message (dict): The received message dict.

    Returns:
        bool: True if successful, False otherwise.
    """
    handlers = {
        Subject.livelog.value: {
            Action.start.value: start_livelogger,
            Action.stop.value: stop_livelogger,
        }
    }

    if "subject" not in message or "action" not in message:
        return False

    handler = handlers.get(message.get("subject")).get(message.get("action"))
    await handler(websocket, message.get("data"))
    return True


@app.websocket_connect()
async def websocket_connected(websocket):
    """
    Sends a `success` message to the websocket client
    on connect.
    """
    if asyncio.iscoroutinefunction(websocket.send_str):
        await websocket.send_str(json.dumps({"subject": Subject.websocket.value, "event": Event.connected.value}))
    else:
        websocket.send_str(json.dumps({"subject": Subject.websocket.value, "event": Event.connected.value}))

    logger.info("new authenticated connection, user: %s", websocket.cirrina.web_session.get("username"))


@app.websocket_message("/api/websocket")
async def websocket_message(websocket, msg):
    """
    On websocket message handler.
    """
    logger.debug("message received from user '%s'", websocket.cirrina.web_session.get("username"))
    try:
        data = json.loads(msg)
        logger.debug("received data %s", str(data))
    except json.decoder.JSONDecodeError:
        logger.error(
            "cannot parse websocket message from user '%s'",
            websocket.cirrina.web_session.get("username"),
        )

    await dispatch(websocket, data)


@app.websocket_disconnect()
async def websocket_closed(_):
    """
    On websocket disconnect handler.
    """
    logger.debug("websocket connection closed")
