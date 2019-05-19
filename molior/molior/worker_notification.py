"""
Async Notification Worker Task
"""

import asyncio

from molior.api import app
from .logger import get_logger

logger = get_logger()
notification_queue = asyncio.Queue()


class NotificationWorker:
    """
    Notification task

    """

    async def run(self):
        """
        Run the worker task.
        """

        while True:
            try:
                task = await notification_queue.get()
                if task is None:
                    logger.info("notification:: got emtpy task, aborting...")
                    break

                notification = task.get("notify")
                if notification:
                    await app.websocket_broadcast(notification)
                    handled = True

                if not handled:
                    logger.error("notification: got unknown task %s", str(task))

                notification_queue.task_done()

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating notification task")
