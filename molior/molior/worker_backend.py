import asyncio

from ..logger import logger
from ..molior.queues import enqueue_task, enqueue_aptly, dequeue_backend, enqueue_backend, buildlogdone
from .backend import Backend
from .notifier import send_mail_notification

from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask

from sqlalchemy import asc


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




    async def _retention_cleanup(self, build_id):

        """
        with Session() as session:
            logger.info(build_id)
            build = session.query(Build).filter(Build.id == build_id).first()
            logger.info(f"Build id {build_id}")
            logger.info(f"Build state {build.buildstate}")

            if build.buildstate == "scheduled":
                logger.info("scheduled")
                time.sleep(10)
                build = session.query(Build).filter(Build.id == build_id).first()
                logger.info({build.buildstate})
        """
        while True:
            with Session() as session:
                logger.info(build_id)
                build = session.query(Build).filter(Build.id == build_id).first()

                if build is not None:
                    for column in build.__table__.columns:
                        column_name = column.name
                        column_value = getattr(build, column_name)
                        logger.info(f"{column_name}: {column_value}")

                if not build:
                    logger.info(f"Build with id {build_id} not found, exiting")
                    break

                #cleanup job for particular projectversion
                #check the buildstate
                #check how many successful builds
                project_version_id = build.projectversion_id
                build_state = build.buildstate
                #check if the buildstate is in an error state, if so skip the cleanup
                neglected_states = ["build_failed", "publish_failed", "already_exists", "already_failed", "nothing_done" ]

                if build_state == "successful":
                    # Execute retention cleanup here when the build is successful
                    logger.info("Build is successful, performing retention cleanup")

                    logger.info(f"Projectversion ID: {project_version_id}")
                    #the number of successful builds to retain per sourcerepository
                    retention_successful_builds = build.projectversion.retention_successful_builds
                    logger.info(f"Number of retention_successful_builds: {retention_successful_builds}")
                    #how many successful builds are for the sourcerepository
                    successful_builds = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "deb",
                        Build.sourcename == build.sourcename,
                        Build.projectversion_id == project_version_id).all()
                    for successful_build in successful_builds:
                        sourcename = successful_build.sourcename
                        build_state = successful_build.buildstate
                        build_id = successful_build.id
                        logger.info(f"Sourcename: {sourcename}, Build State: {build_state}, Build Id: {build_id}")
                    # count how many successful builds there are for the projectversion
                    successful_builds_number = len(successful_builds)
                    logger.info(f"Number of Successful Builds: {successful_builds_number}")

                    # how many builds should be deleted
                    builds_to_delete = successful_builds_number - retention_successful_builds
                    logger.info(f"Number of builds to delete: {builds_to_delete}")
                    # if there are more than the retention successful builds, give the list of the oldest build
                    oldest_builds_to_delete = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "deb",
                        Build.sourcename == build.sourcename,
                        Build.projectversion_id == project_version_id
                        ).order_by(asc(Build.startstamp)).limit(builds_to_delete).all()
                    for oldest_build in oldest_builds_to_delete:
                        sourcename = oldest_build.sourcename
                        start_stamp = oldest_build.startstamp
                        logger.info(f"Sourcename: {sourcename}, Start stamp: {start_stamp}")

                    # for example: if there are 3 successful builds, but retention_successful builds is 1, the oldest build needs to be deleted
                    # delete the oldest build
                    # take the oldest build

                    oldest_build_to_delete = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "deb",
                        Build.sourcename == build.sourcename,
                        Build.projectversion_id == project_version_id
                        ).order_by(asc(Build.startstamp)).first()

                    if oldest_build_to_delete:
                        sourcename = oldest_build_to_delete.sourcename
                        start_stamp = oldest_build_to_delete.startstamp
                        build_id = oldest_build_to_delete.id
                        logger.info(f"Sourcename: {sourcename}, Start stamp: {start_stamp}, Build ID: {build_id}")
                    else:
                        logger.info("No oldest build found")

                    # check how many successful builds are now and if the correct build got deleted
                    # create new projectversion, use some package (1 sorce, 1 debian package), in this version then it should delete also the topbuild and source package

                    await enqueue_aptly({"delete_deb_build": [build_id]})
                    break
                    # await enqueue_aptly({"delete_build": [build_id]})

                elif build_state in neglected_states:
                    logger.info(f"Build is in the state ({build_state}), skipping retention cleanup")
                    break

                else:
                    logger.info(f"Build is in the state ({build_state}), waiting for 5 seconds and checking again")
                    await asyncio.sleep(5)

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
