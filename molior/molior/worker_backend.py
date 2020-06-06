import asyncio

from ..app import logger
from ..tools import write_log
from .backend import Backend
from .notifier import send_mail_notification
from ..molior.core import get_target_arch, get_apt_repos
from .configuration import Configuration

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

    async def startup_scheduling(self):
        with Session() as session:

            scheduled_builds = session.query(Build, BuildTask).filter(Build.buildstate == "scheduled", Build.buildtype == "deb",
                                                                      BuildTask.build_id == Build.id).all()
            if not scheduled_builds:
                return

            config = Configuration()
            apt_url = config.aptly.get("apt_url")

            for build in scheduled_builds:
                arch = build.buildconfiguration.buildvariant.architecture.name
                base_mirror_db = build.buildconfiguration.buildvariant.base_mirror
                distrelease_name = base_mirror_db.project.name
                distrelease_version = base_mirror_db.name
                project_version = build.buildconfiguration.projectversions[0]
                apt_urls = get_apt_repos(project_version, session, is_ci=build.is_ci)
                arch_any_only = False if arch == get_target_arch(build, session) else True

                logger.info(build)
                job = [
                    build.id,
                    build.buildtask.task_id,
                    build.version,
                    apt_url,
                    arch,
                    arch_any_only,
                    distrelease_name,
                    distrelease_version,
                    "unstable" if build.is_ci else "stable",
                    build.sourcename,
                    project_version.project.name,
                    project_version.name,
                    apt_urls,
                ]
                self._schedule(job)

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

        await self.startup_scheduling()

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
