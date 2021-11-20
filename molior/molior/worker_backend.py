from ..app import logger
from .backend import Backend
from .notifier import send_mail_notification
from ..molior.queues import enqueue_task, enqueue_aptly, dequeue_backend, enqueue_backend, buildlogdone

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
        await backend.build(*job)

    async def _started(self, build_id):
        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("build_started: no build found for %d", build_id)
                return
            await build.parent.parent.log("I: started build for %s %s\n" % (build.projectversion.fullname, build.sourcename))
            await build.set_building()
            session.commit()

    async def _succeeded(self, build_id):
        self.build_outcome[build_id] = True
        if build_id in self.logging_done:
            await enqueue_backend({"terminate": build_id})

    async def _failed(self, build_id):
        self.build_outcome[build_id] = False
        if build_id in self.logging_done:
            await enqueue_backend({"terminate": build_id})

    async def _logging_done(self,  build_id):
        self.logging_done.append(build_id)
        if build_id in self.build_outcome:
            await enqueue_backend({"terminate": build_id})

    async def _terminate(self, build_id):
        outcome = self.build_outcome[build_id]
        del self.build_outcome[build_id]
        self.logging_done.remove(build_id)

        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("build_failed: no build found for %d", build_id)
                return

            if outcome:  # build successful
                await build.set_needs_publish()
                await enqueue_aptly({"publish": [build_id]})
            else:        # build failed
                await build.parent.parent.log("I: build for %s %s failed\n" % (build.projectversion.fullname, build.sourcename))
                await build.set_failed()
                await buildlogdone(build.id)
                session.commit()

                buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
                if buildtask:
                    session.delete(buildtask)
                    session.commit()

                if not build.is_ci:
                    send_mail_notification(build)

    async def _abort(self, build_id):
        b = Backend()
        backend = b.get_backend()
        await backend.abort(build_id)

    async def run(self):
        """
        Run the worker task.
        """

        while True:
            task = await dequeue_backend()
            if task is None:
                break

            try:
                handled = False
                job = task.get("schedule")
                if job:
                    handled = True
                    await self._schedule(job)
                build_id = task.get("abort")
                if build_id:
                    handled = True
                    await self._abort(build_id)
                build_id = task.get("started")
                if build_id:
                    handled = True
                    await self._started(build_id)
                build_id = task.get("succeeded")
                if build_id:
                    handled = True
                    await self._succeeded(build_id)
                build_id = task.get("failed")
                if build_id:
                    handled = True
                    await self._failed(build_id)
                build_id = task.get("terminate")
                if build_id:
                    handled = True
                    await self._terminate(build_id)
                build_id = task.get("logging_done")
                if build_id:
                    handled = True
                    await self._logging_done(build_id)
                node_dummy = task.get("node_registered")
                if node_dummy:
                    # Schedule builds
                    args = {"schedule": []}
                    await enqueue_task(args)
                    handled = True

                if not handled:
                    logger.error("backend: got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("backend task terminated")
