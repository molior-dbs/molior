from ..logger import logger

from .queues import dequeue_notification


class NotificationWorker:
    """
    Notification task

    """

    async def run(self, app):
        """
        Run the worker task.
        """

        while True:
            handled = False
            try:
                task = await dequeue_notification()
                if task is None:
                    break

                notification = task.get("notify")
                if notification:
                    await app.websocket_broadcast(notification)
                    handled = True

                if not handled:
                    logger.error("notification: got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("notification task terminated")
