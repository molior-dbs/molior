import asyncio

from ..app import logger
from ..tools import write_log
from .backend import Backend
from .notifier import send_mail_notification

from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask

backend_queue = asyncio.Queue()


class BackendWorker:
    """
    Backend task

    """

    def __init__(self, task_queue, aptly_queue):
        self.task_queue = task_queue
        self.aptly_queue = aptly_queue
        self.logging_done = []
        self.build_outcome = {}  # build_id: outcome

    async def startup_scheduling(self):
        with Session() as session:

            scheduled_builds = session.query(Build).filter(Build.buildstate == "scheduled", Build.buildtype == "deb").all()
            if scheduled_builds:
                for build in scheduled_builds:
                    buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
                    session.delete(buildtask)
                    await build.set_needs_build()
                session.commit()

            building_builds = session.query(Build).filter(Build.buildstate == "building", Build.buildtype == "deb").all()
            if building_builds:
                for build in building_builds:
                    buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
                    session.delete(buildtask)
                    await build.set_failed()
                session.commit()

    async def _schedule(self, job):
        b = Backend()
        backend = b.get_backend()
        backend.build(*job)

    async def _started(self, session, build_id):
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build_started: no build found for %d", build_id)
            return
        await write_log(build.parent.parent.id, "I: started build %d\n" % build_id)
        await build.set_building()
        session.commit()

    async def _succeeded(self, session, build_id):
        self.build_outcome[build_id] = True
        if build_id in self.logging_done:
            await backend_queue.put({"terminate": build_id})

    async def _failed(self, session, build_id):
        self.build_outcome[build_id] = False
        if build_id in self.logging_done:
            await backend_queue.put({"terminate": build_id})

    async def _logging_done(self, session, build_id):
        self.logging_done.append(build_id)
        if build_id in self.build_outcome:
            await backend_queue.put({"terminate": build_id})

    async def _terminate(self, session, build_id):
        outcome = self.build_outcome[build_id]
        del self.build_outcome[build_id]
        self.logging_done.remove(build_id)

        if outcome:  # build successful
            await self.aptly_queue.put({"publish": [build_id]})
        else:        # build failed
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("build_failed: no build found for %d", build_id)
                return
            await write_log(build.parent.parent.id, "E: build %d failed\n" % build_id)
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

        await self.startup_scheduling()

        while True:
            try:
                task = await backend_queue.get()
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
                        await self.task_queue.put(args)
                        handled = True

                if not handled:
                    logger.error("backend: got unknown task %s", str(task))

                backend_queue.task_done()

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating backend task")
