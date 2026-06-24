from ..logger import logger

from .queues import dequeue_notification


class NotificationWorker:
    """
    Notification task

    """

    async def run(self, broadcast):
        """
        Run the worker task.

        broadcast: async callable(dict) that fans the notification out to
                   all connected clients (SSE subscribers, etc.).
        """

        while True:
            handled = False
            try:
                task = await dequeue_notification()
                if task is None:
                    break

                notification = task.get("notify")
                if notification:
                    await broadcast(notification)
                    handled = True

                if not handled:
                    logger.error("notification: got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("notification task terminated")
