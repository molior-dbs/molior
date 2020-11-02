import shutil
import asyncio
import giturlparse

from ..app import logger
from ..ops import GitClone, get_latest_tag
from ..ops import BuildProcess, ScheduleBuilds, CreateBuildEnv
from ..molior.configuration import Configuration
from ..molior.queues import enqueue_task, dequeue_task, enqueue_aptly

from ..model.database import Session
from ..model.build import Build
from ..model.chroot import Chroot
from ..model.sourcerepository import SourceRepository
from ..model.sourepprover import SouRepProVer


async def cleanup_builds():
    """
    Cleanup existing builds on startup
    """

    cleaned_up = False
    with Session() as session:
        # FIXME: set schedules to needs build and delete buildtask
        builds = session.query(Build).filter(Build.buildstate == "building").all()
        for build in builds:
            await build.set_failed()
            if build.buildtask:
                session.delete(build.buildtask)
            cleaned_up = True

        builds = session.query(Build).filter(Build.buildstate == "publishing").all()
        for build in builds:
            await build.set_publish_failed()
            if build.buildtask:
                session.delete(build.buildtask)
            cleaned_up = True

        if cleaned_up:
            session.commit()


def cleanup_repos():
    """
    Cleanup existing repos on startup
    """

    with Session() as session:
        repos = session.query(SourceRepository).filter(SourceRepository.name.is_(None)).all()
        for repo in repos:
            try:
                repoinfo = giturlparse.parse(repo.url)
            except giturlparse.parser.ParserError:
                logger.warning("error parsing git url: {}".format(repo.url))
                continue
            repo.name = repoinfo.name

        if repos:
            session.commit()


class Worker:
    """
    Main worker task

    """

    def __init__(self):
        self.chroot_build_count = 0

    async def _clone(self, args, session):
        logger.debug("worker: got clone task")
        build_id = args[0]
        repo_id = args[1]

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("clone: build %d not found", build_id)
            return

        repo = session.query(SourceRepository).filter(SourceRepository.id == repo_id).first()
        if not repo:
            logger.error("buildlatest: repo %d not found", repo_id)
            return

        if repo.state != "new" and repo.state != "error":
            logger.error("Repository with id '%d' not ready for clone, ignoring request", repo_id)
            return

        repo.set_cloning()
        session.commit()

        asyncio.ensure_future(GitClone(build.id, repo.id, session))

    async def _build(self, args, session):
        logger.debug("worker: got build task")

        build_id = args[0]
        repo_id = args[1]
        git_ref = args[2]
        ci_branch = args[3]
        targets = args[4]
        force_ci = args[4]

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build: build %d not found", build_id)
            return

        repo = session.query(SourceRepository).filter(SourceRepository.id == repo_id).first()
        if not repo:
            logger.error("build: repo %d not found", repo_id)
            return

        if repo.state == "error":
            await build.log("E: git repo is in error state\n")
            await build.set_failed()
            return

        if repo.state != "ready":
            logger.info("worker: repo %d not ready, requeueing", repo_id)
            await enqueue_task({"build": args})
            await asyncio.sleep(2)
            return

        if build.buildstate != "building":
            await build.set_building()

        repo.set_busy()
        session.commit()

        asyncio.ensure_future(BuildProcess(build_id, repo.id,
                                           git_ref, ci_branch, targets, force_ci))

    async def _buildlatest(self, args, session):
        logger.debug("worker: got buildlatest task")
        repo_id = args[0]
        build_id = args[1]

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("buildlatest: build %d not found", build_id)
            return

        repo = session.query(SourceRepository).filter(SourceRepository.id == repo_id).first()
        if not repo:
            logger.error("buildlatest: repo %d not found", repo_id)
            return

        if repo.state == "error":
            await build.log("E: git repo is in error state\n")
            await build.set_failed()
            return

        if repo.state != "ready":
            await enqueue_task({"buildlatest": args})
            logger.info("worker: repo %d not ready, requeueing", repo_id)
            await asyncio.sleep(2)
            return

        if build.buildstate != "building":
            await build.set_building()

        repo.set_busy()
        session.commit()

        await build.logtitle("Checking Repository")

        await build.log("I: fetching git tags\n")
        try:
            # this does a git fetch
            latest_tag = await get_latest_tag(repo.src_path, build_id)
        except Exception as exc:
            logger.error("worker: error getting latest git tag")
            await build.log("E: Error getting git tags\n")
            await build.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await build.logdone()
            logger.exception(exc)
            await build.set_failed()
            repo.set_ready()
            session.commit()
            return

        repo.set_ready()
        session.commit()

        if not latest_tag:
            logger.error("sourcerepository '%s' has no release tag", repo.url)
            await build.log("E: no git tags found\n")
            await build.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await build.logdone()
            await build.set_failed()
            session.commit()
            return

        await build.log("\n")
        git_ref = str(latest_tag)
        args = {"build": [build_id, repo_id, git_ref, None, None, False]}
        await enqueue_task(args)

    async def _rebuild(self, args, session):
        logger.debug("worker: got rebuild task")
        build_id = args[0]
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("rebuild: build %d not found", build_id)
            return

        ok = False
        if build.buildtype == "deb":
            if build.buildstate == "build_failed" or \
               build.buildstate == "publish_failed":
                ok = True
                buildout = "/var/lib/molior/buildout/%d" % build_id
                logger.info("removing %s", buildout)
                try:
                    shutil.rmtree(buildout)
                except Exception as exc:
                    logger.exception(exc)
                    pass

                await build.set_needs_build()
                session.commit()

                args = {"schedule": []}
                await enqueue_task(args)

        if build.buildtype == "source":
            if build.buildstate == "publish_failed":
                ok = True
                await build.set_needs_publish()
                session.commit()
                await build.parent.log("I: publishing source package\n")
                await enqueue_aptly({"src_publish": [build.id]})

        if build.buildtype == "chroot":
            if build.buildstate == "build_failed":
                ok = True
                chroot = session.query(Chroot).filter(Chroot.build_id == build_id).first()
                if chroot:
                    args = {"buildenv": [
                            chroot.id,
                            build_id,
                            chroot.basemirror.mirror_distribution,
                            chroot.basemirror.project.name,
                            chroot.basemirror.name,
                            chroot.architecture,
                            chroot.basemirror.mirror_components,
                            chroot.get_mirror_url(),
                            chroot.get_mirror_keys(),
                            ]}
                    await enqueue_task(args)
                    ok = True

        if not ok:
            logger.error("rebuilding {} build in state {} not supported".format(build.buildtype, build.buildstate))

    async def _schedule(self, _):
        asyncio.ensure_future(ScheduleBuilds())

    async def _buildenv(self, args):
        cfg = Configuration()
        max_parallel_chroots = cfg.max_parallel_chroots
        if max_parallel_chroots and type(max_parallel_chroots) is int and max_parallel_chroots > 0:
            if self.chroot_build_count >= max_parallel_chroots:
                await enqueue_task({"buildenv": args})
                logger.info("worker: building %d chroots already, requeueing...", self.chroot_build_count)
                await asyncio.sleep(2)
                return

        self.chroot_build_count += 1

        chroot_id = args[0]
        build_id = args[1]
        dist = args[2]
        name = args[3]
        version = args[4]
        arch = args[5]
        components = args[6]
        repo_url = args[7]
        mirror_keys = args[8]
        asyncio.ensure_future(self.create_build_env(chroot_id, build_id, dist, name, version,
                              arch, components, repo_url, mirror_keys))

    async def create_build_env(self, chroot_id, build_id, dist, name, version, arch, components, repo_url, mirror_keys):
        await CreateBuildEnv(chroot_id, build_id, dist,
                             name, version, arch, components, repo_url, mirror_keys)
        self.chroot_build_count -= 1

    async def _merge_duplicate_repo(self, args, session):
        repository_id = args[0]
        duplicate_id = args[1]

        original = session.query(SourceRepository).filter(SourceRepository.id == repository_id).first()
        if not original:
            logger.error("merge: repo %d not found", repository_id)
            return

        duplicate = session.query(SourceRepository).filter(SourceRepository.id == duplicate_id).first()
        if not duplicate:
            logger.error("merge: duplicate %d not found", duplicate_id)
            return

        if original.state != "ready":
            logger.info("worker: repo %d not ready, requeueing", repository_id)
            await enqueue_task({"merge_duplicate_repo": args})
            await asyncio.sleep(2)
            return

        if duplicate.state != "ready" or duplicate.state != "error":  # merge duplicates in error state
            logger.info("worker: repo %d not ready, requeueing", duplicate_id)
            await enqueue_task({"merge_duplicate_repo": args})
            await asyncio.sleep(2)
            return

        original.set_busy()
        duplicate.set_busy()
        session.commit()

        builds = session.query(Build).filter(Build.sourcerepository_id == duplicate.id).all()
        for build in builds:
            build.sourcerepository_id = original.id

        # find all projectversion contaning duplicate
        sourepprovers = session.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == duplicate.id).all()
        for sourepprover in sourepprovers:
            # we check if original is in the projectversion already
            t = session.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == original.id,
                SouRepProVer.projectversion_id == sourepprover.projectversion_id).first()
            if t:
                # delete duplicate from projectversion
                session.delete(sourepprover)
            else:
                # replace duplicate with original
                sourepprover.sourcerepository_id = original.id

        session.delete(duplicate)

        try:
            shutil.rmtree("/var/lib/molior/repositories/%d" % duplicate_id)
        except Exception as exc:
            logger.exception(exc)

        original.set_ready()
        session.commit()

    async def _delete_repo(self, args, session):
        repository_id = args[0]

        repo = session.query(SourceRepository).filter(SourceRepository.id == repository_id).first()

        if not repo:
            logger.error("merge: repo %d not found", repository_id)
            return

        if repo.state != "ready" or repo.state != "error":
            logger.info("worker: repo %d not ready, requeueing", repository_id)
            await enqueue_task({"delete_repo": args})
            await asyncio.sleep(2)
            return

        repo.set_busy()
        session.commit()
        logger.info("worker: deleting repo %d", repository_id)
        session.commit()
        session.delete(repo)
        shutil.rmtree("/var/lib/molior/repositories/%d" % repository_id, ignore_errors=True)  # not fail on read-only files
        session.commit()

    async def run(self):
        """
        Run the worker task.
        """

        # Cleanup
        try:
            await cleanup_builds()
        except Exception as exc:
            logger.exception(exc)

        try:
            cleanup_repos()
        except Exception as exc:
            logger.exception(exc)

        while True:
            session = None
            try:
                task = await dequeue_task()
                if task is None:
                    logger.info("worker: got emtpy task, aborting...")
                    break

                logger.debug("worker: got task {}".format(task))
                with Session() as session:

                    handled = False
                    args = task.get("clone")
                    if args:
                        handled = True
                        await self._clone(args, session)

                    if not handled:
                        args = task.get("build")
                        if args:
                            handled = True
                            await self._build(args, session)

                    if not handled:
                        args = task.get("buildlatest")
                        if args:
                            handled = True
                            await self._buildlatest(args, session)

                    if not handled:
                        args = task.get("rebuild")
                        if args:
                            handled = True
                            await self._rebuild(args, session)

                    if not handled:
                        args = task.get("schedule")
                        if args == []:
                            handled = True
                            await self._schedule(session)

                    if not handled:
                        args = task.get("buildenv")
                        if args:
                            handled = True
                            await self._buildenv(args)

                    if not handled:
                        args = task.get("merge_duplicate_repo")
                        if args:
                            handled = True
                            await self._merge_duplicate_repo(args, session)

                    if not handled:
                        args = task.get("delete_repo")
                        if args:
                            handled = True
                            await self._delete_repo(args, session)

                    if not handled:
                        logger.error("worker got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating worker task")
