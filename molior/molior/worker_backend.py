from ..app import logger
from .backend import Backend
from .notifier import send_mail_notification
from ..molior.queues import enqueue_task, enqueue_aptly, dequeue_backend, enqueue_backend

from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask


class BackendWorker:
    """
    Backend task

    """

    def __init__(self):
        self.logging_done = []
        self.build_outcome = {}  # build_id: outcome

    async def _schedule(self, job):
        b = Backend()
        backend = b.get_backend()
        backend.build(*job)

    async def _started(self, session, build_id):
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build_started: no build found for %d", build_id)
            return
        build.parent.parent.log("I: started build %d\n" % build_id)
        await build.set_building()
        session.commit()

    async def _succeeded(self, session, build_id):
        self.build_outcome[build_id] = True
        if build_id in self.logging_done:
            enqueue_backend({"terminate": build_id})

    async def _failed(self, session, build_id):
        self.build_outcome[build_id] = False
        if build_id in self.logging_done:
            enqueue_backend({"terminate": build_id})

    async def _logging_done(self, session, build_id):
        self.logging_done.append(build_id)
        if build_id in self.build_outcome:
            enqueue_backend({"terminate": build_id})

    async def _terminate(self, session, build_id):
        outcome = self.build_outcome[build_id]
        del self.build_outcome[build_id]
        self.logging_done.remove(build_id)

        if outcome:  # build successful
            enqueue_aptly({"publish": [build_id]})
        else:        # build failed
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("build_failed: no build found for %d", build_id)
                return
            build.parent.parent.log("E: build %d failed\n" % build_id)
            await build.set_failed()
            session.commit()

            buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
            session.delete(buildtask)
            session.commit()

            if not build.is_ci:
                send_mail_notification(build)

    async def run(self):
        """
        Run the worker task.
        """

        while True:
            try:
                task = await dequeue_backend()
                if task is None:
                    logger.info("backend: got emtpy task, aborting...")
                    break

                logger.debug("backend: got task {}".format(task))
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
                    build_id = task.get("terminate")
                    if build_id:
                        handled = True
                        await self._terminate(session, build_id)
                    build_id = task.get("logging_done")
                    if build_id:
                        handled = True
                        await self._logging_done(session, build_id)
                    node_dummy = task.get("node_registered")
                    if node_dummy:
                        # Schedule builds
                        args = {"schedule": []}
                        enqueue_task(args)
                        handled = True

                if not handled:
                    logger.error("backend: got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating backend task")
