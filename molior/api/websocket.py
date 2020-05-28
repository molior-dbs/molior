import asyncio
import json

from pathlib import Path

from molior.app import app, logger
from molior.molior.notifier import Subject, Event, Action

BUILD_OUT_PATH = Path("/var/lib/molior/buildout")


class LiveLogger:
    """
    Provides helper functions for livelogging on molior.
    """

    def __init__(self, sender, file_path):
        self.__sender = sender
        self.__filepath = file_path
        self.__up = False

    async def stop(self):
        """
        Stops the livelogging loop.
        """
        self.__up = False

    async def start(self):
        """
        Starts the livelogging.
        """
        self.__up = True
        try:
            with self.__filepath.open() as log_file:
                while self.__up:
                    data = log_file.read(8192)
                    if not data:
                        await asyncio.sleep(1)
                        logger.info("buildlog no read")
                        continue
                    logger.info("buildlog read {}".format(len(data)))
                    message = {
                        "event": Event.added.value,
                        "subject": Subject.buildlog.value,
                        "data": data,
                    }
                    await self.__sender(json.dumps(message))
                    await asyncio.sleep(0.1)
                    # if line.startswith("Finished"):
                    #    await self.stop()
        except FileNotFoundError:
            logger.error("livelogger: log file not found: {}".format(self.__filepath))
        except Exception as exc:
            logger.error("livelogger: error sending live logs")
            logger.exception(exc)


async def start_livelogger(websocket, data):
    """
    Starts the livelogger for the given
    websocket client.

    Args:
        websocket: The websocket instance.
        data (dict): The received data.
    """
    logger.info("start_livelogger {}".format(data))
    if "build_id" not in data:
        return False

    path = BUILD_OUT_PATH / str(data.get("build_id")) / "build.log"
    llogger = LiveLogger(websocket.send_str, path)

    if hasattr(websocket, "logger") and websocket.logger:
        await stop_livelogger(websocket, data)

    websocket.logger = llogger
    # FIXME: use separate thread for file IO
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
        Subject.buildlog.value: {
            Action.start.value: start_livelogger,
            Action.stop.value: stop_livelogger,
        }
    }

    if "subject" not in message or "action" not in message:
        logger.error("unknown websocket message recieved: {}".format(message))
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
    logger.info("message received from user '%s'", websocket.cirrina.web_session.get("username"))
    try:
        data = json.loads(msg)
        logger.debug("received data %s", str(data))
    except json.decoder.JSONDecodeError:
        logger.error("cannot parse websocket message from user '%s'", websocket.cirrina.web_session.get("username"))

    await dispatch(websocket, data)


@app.websocket_disconnect()
async def websocket_closed(_):
    """
    On websocket disconnect handler.
    """
    logger.debug("websocket connection closed")
