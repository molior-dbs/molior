"""
Async Backend Worker Task
"""

import asyncio

from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask
from .logger import get_logger
from .notifier import send_mail_notification
from molior.molior.backend import Backend
from molior.molior.buildlogger import write_log


logger = get_logger()
backend_queue = asyncio.Queue()


class BackendWorker:
    """
    Backend task

    """

    def __init__(self, task_queue, aptly_queue):
        self.task_queue = task_queue
        self.aptly_queue = aptly_queue

    async def _schedule(self, job):
        b = Backend()
        backend = b.get_backend()
        backend.build(*job)

    async def _started(self, session, build_id):
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build_started: no build found for %d", build_id)
            return
        write_log(build.parent.parent.id, "I: started build %d\n" % build_id)
        await build.set_building()
        session.commit()

    async def _succeeded(self, session, build_id):
        await self.aptly_queue.put({"publish": [build_id]})

    async def _failed(self, session, build_id):
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build_failed: no build found for %d", build_id)
            return
        write_log(build.parent.parent.id, "E: build %d failed\n" % build_id)
        await build.set_failed()
        session.commit()

        buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
        session.delete(buildtask)
        session.commit()

        # FIXME: do not remove the logs!
        # src_repo = build.buildconfiguration.sourcerepositories[0]
        # for _file in src_repo.path.glob("*_{}*.*".format(build.version)):
        #    logger.info("removing: %s", _file)
        #    os.remove(str(_file))

        if not build.is_ci:
            send_mail_notification(build)

    async def run(self):
        """
        Run the worker task.
        """

        while True:
            try:
                task = await backend_queue.get()
                if task is None:
                    logger.info("backend:: got emtpy task, aborting...")
                    break

                with Session() as session:
                    handled = False
                    job = task.get("schedule")
                    if job:
                        handled = True
                        await self._schedule(job)
                    build_id = task.get("started")
                    if build_id:
                        handled = True
                        await self._started(session, build_id)
                    build_id = task.get("succeeded")
                    if build_id:
                        handled = True
                        await self._succeeded(session, build_id)
                    build_id = task.get("failed")
                    if build_id:
                        handled = True
                        await self._failed(session, build_id)

                if not handled:
                    logger.error("backend: got unknown task %s", str(task))

                backend_queue.task_done()

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating backend task")
