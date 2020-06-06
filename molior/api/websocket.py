import asyncio
import json

from pathlib import Path
from aiofile import AIOFile, Reader

from molior.app import app, logger
from molior.molior.notifier import Subject, Event, Action
from molior.model.database import Session
from molior.model.build import Build

BUILD_OUT_PATH = Path("/var/lib/molior/buildout")


class LiveLogger:
    """
    Provides helper functions for livelogging on molior.
    """

    def __init__(self, sender, build_id):
        self.__sender = sender
        self.build_id = build_id
        self.__up = False
        self.__filepath = BUILD_OUT_PATH / str(build_id) / "build.log"

    def stop(self):
        """
        Stops the livelogging
        """
        logger.info("build-{}: stopping livelogger".format(self.build_id))
        self.__up = False

    async def check_abort(self):
        with Session() as session:
            build = session.query(Build).filter(Build.id == self.build_id).first()
            if not build:
                logger.error("build: build %d not found", self.build_id)
                message = {"subject": Subject.buildlog.value, "event": Event.removed.value}
                await self.__sender(json.dumps(message))
                self.stop()
                return True
            if build.buildstate == "build_failed" or \
               build.buildstate == "publish_failed" or \
               build.buildstate == "successful":
                logger.info("buildlog: end of build {}".format(self.build_id))
                message = {"subject": Subject.buildlog.value, "event": Event.removed.value}
                await self.__sender(json.dumps(message))
                self.stop()
                return True
        return False

    async def start(self):
        """
        Starts the livelogging
        """
        logger.info("build-{}: starting livelogger".format(self.build_id))
        self.__up = True
        while self.__up:
            try:
                async with AIOFile(str(self.__filepath), "rb") as log_file:
                    reader = Reader(log_file, chunk_size=16384)
                    retries = 0
                    while self.__up:
                        async for data in reader:
                            message = {"event": Event.added.value, "subject": Subject.buildlog.value, "data": str(data, 'utf-8')}
                            await self.__sender(json.dumps(message))

                        # EOF
                        if retries % 100 == 0:
                            retries = 0
                            if self.check_abort():
                                continue  # self.__up will be falsem drop out of for loops
                        await asyncio.sleep(.1)
                        retries += 1
                        continue
            except FileNotFoundError:
                await asyncio.sleep(1)
                self.check_abort()
            except Exception as exc:
                logger.error("livelogger: error sending live logs")
                logger.exception(exc)
                self.stop()


async def start_livelogger(websocket, data):
    """
    Starts the livelogger for the given
    websocket client.

    Args:
        websocket: The websocket instance.
        data (dict): The received data.
    """
    if "build_id" not in data:
        logger.error("livelogger: no build ID found")
        return False

    llogger = LiveLogger(websocket.send_str, data.get("build_id"))

    if hasattr(websocket, "logger") and websocket.logger:
        logger.error("livelogger: removing existing livelogger")
        await stop_livelogger(websocket, data)

    websocket.logger = llogger
    loop = asyncio.get_event_loop()
    loop.create_task(llogger.start())


async def stop_livelogger(websocket, _):
    """
    Stops the livelogger.
    """
    if hasattr(websocket, "logger") and websocket.logger:
        websocket.logger.stop()
    else:
        logger.error("stop_livelogger: no active logger found")


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
    try:
        data = json.loads(msg)
    except json.decoder.JSONDecodeError:
        logger.error("cannot parse websocket message from user '%s'", websocket.cirrina.web_session.get("username"))

    if "subject" not in data or "action" not in data:
        logger.error("unknown websocket message recieved: {}".format(data))
        return

    if data.get("subject") != Subject.buildlog.value:
        logger.error("unknown websocket message recieved: {}".format(data))
        return

    if data.get("action") == Action.start.value:
        await start_livelogger(websocket, data.get("data"))
    elif data.get("action") == Action.stop.value:
        await stop_livelogger(websocket, data.get("data"))
    else:
        logger.error("unknown websocket message recieved: {}".format(data))
        return


@app.websocket_disconnect()
async def websocket_closed(_):
    """
    On websocket disconnect handler.
    """
    logger.debug("websocket connection closed")
