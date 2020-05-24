import asyncio
import json

from molior.app import logger
from molior.notifier import Subject, Event


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
                # Go to the end of the file
                log_file.seek(0, 2)
                while self.__up:
                    line = log_file.readline()
                    if not line:
                        await asyncio.sleep(0.1)
                        continue
                    data = {
                        "message": {
                            "event": Event.added.value,
                            "subject": Subject.livelog.value,
                            "data": line,
                        },
                        "status": 200,
                    }
                    self.__sender(json.dumps(data))
                    if line.startswith("Finished"):
                        await self.stop()
        except FileNotFoundError:
            logger.error("livelogger: log file not found: {}".format(self.__filepath))
        except Exception as exc:
            logger.error("livelogger: error sending life logs")
            logger.exception(exc)
