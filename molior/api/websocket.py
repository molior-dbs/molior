import asyncio
import json

from pathlib import Path
from aiofile import AIOFile, Reader

from molior.app import app, logger
from molior.molior.notifier import Subject, Event, Action
from molior.model.database import Session
from molior.model.build import Build

BUILD_OUT_PATH = Path("/var/lib/molior/buildout")


class BuildLogger:
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
        logger.debug("build-{}: stopping buildlogger".format(self.build_id))
        self.__up = False

    async def check_abort(self):
        with Session() as session:
            build = session.query(Build).filter(Build.id == self.build_id).first()
            if not build:
                logger.error("build: build %d not found", self.build_id)
                return True
            if build.buildstate == "build_failed" or \
               build.buildstate == "publish_failed" or \
               build.buildstate == "successful":
                return True
        return False

    async def start(self):
        """
        Starts the livelogging
        """
        logger.debug("build-{}: starting buildlogger".format(self.build_id))
        self.__up = True
        while self.__up:
            try:
                async with AIOFile(str(self.__filepath), "rb") as log_file:
                    reader = Reader(log_file, chunk_size=16384)
                    retries = 0
                    while self.__up:
                        async for data in reader:
                            logger.info("sending")
                            message = {"event": Event.added.value, "subject": Subject.buildlog.value, "data": str(data, 'utf-8')}
                            await self.__sender(json.dumps(message))

                        # EOF
                        if retries % 100 == 0:
                            retries = 0
                            if self.check_abort():
                                self.stop()
                                break
                        retries += 1
                        await asyncio.sleep(.1)
            except FileNotFoundError:
                await asyncio.sleep(1)
                self.check_abort()
            except Exception as exc:
                logger.error("buildlogger: error sending buildlogs")
                logger.exception(exc)
                self.stop()

        message = {"subject": Subject.buildlog.value, "event": Event.done.value}
        await self.__sender(json.dumps(message))


async def start_buildlogger(ws, data):
    """
    Starts the buildlogger for the given
    websocket client.

    Args:
        websocket: The websocket instance.
        data (dict): The received data.
    """
    if "build_id" not in data:
        logger.error("buildlogger: no build ID found")
        return False

    if hasattr(ws, "molior_buildlogger") and ws.molior_buildlogger:
        await stop_buildlogger(ws)

    molior_buildlogger = BuildLogger(ws.send_str, data.get("build_id"))
    ws.molior_buildlogger = molior_buildlogger
    loop = asyncio.get_event_loop()
    loop.create_task(molior_buildlogger.start())


async def stop_buildlogger(ws):
    """
    Stops the buildlogger.
    """
    if hasattr(ws, "molior_buildlogger") and ws.molior_buildlogger:
        ws.molior_buildlogger.stop()
        delattr(ws, "molior_buildlogger")


@app.websocket_connect()
async def websocket_connected(ws):
    """
    Sends a 'connected' message to the websocket client on connect.
    """
    await ws.send_str(json.dumps({"subject": Subject.websocket.value, "event": Event.connected.value}))
    logger.info("websocket: new connection from user %s", ws.cirrina.web_session.get("username"))


@app.websocket_message("/api/websocket")
async def websocket_message(ws, msg):
    """
    On websocket message handler.
    """
    try:
        data = json.loads(msg)
    except json.decoder.JSONDecodeError:
        logger.error("cannot parse websocket message from user '%s'", ws.cirrina.web_session.get("username"))

    if "subject" not in data or "action" not in data:
        logger.error("unknown websocket message recieved: {}".format(data))
        return

    if data.get("subject") != Subject.buildlog.value:
        logger.error("unknown websocket message recieved: {}".format(data))
        return

    if data.get("action") == Action.start.value:
        await start_buildlogger(ws, data.get("data"))
    elif data.get("action") == Action.stop.value:
        await stop_buildlogger(ws)
    else:
        logger.error("unknown websocket message recieved: {}".format(data))
        return


@app.websocket_disconnect()
async def websocket_closed(ws):
    """
    On websocket disconnect handler.
    """
    logger.debug("websocket connection closed")
    if hasattr(ws, "molior_buildlogger"):
        delattr(ws, "molior_buildlogger")
