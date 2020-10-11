import asyncio
import operator

from sqlalchemy import or_

from ..app import logger
from ..tools import get_aptly_connection, write_log, write_log_title, db2array, array2db
from ..ops import DebSrcPublish, DebPublish
from ..aptly.errors import AptlyError, NotFoundError
from .debianrepository import DebianRepository
from .notifier import Subject, Event, notify, send_mail_notification

from ..model.database import Session
from ..model.build import Build
from ..model.project import Project
from ..model.projectversion import ProjectVersion
from ..model.chroot import Chroot
from ..model.mirrorkey import MirrorKey


async def startup_migration(task_queue):
    """
    Migrate old aptly repos
    """
    aptly = get_aptly_connection()

    with Session() as session:
        # get mirrors in updating state
        query = session.query(ProjectVersion).join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(False))

        if not query.count():
            return

        aptly_repos = await aptly.repo_get()
        projectversions = query.all()
        for projectversion in projectversions:
            repo_name = "%s-%s-%s-%s" % (projectversion.basemirror.project.name, projectversion.basemirror.name,
                                         projectversion.project.name, projectversion.name)

            aptly_snapshots = await aptly.snapshot_get()
            for aptly_snapshot in aptly_snapshots:
                aptly_snapshot_name = aptly_snapshot.get("Name")
                publish_name = "{}_{}_repos_{}_{}".format(projectversion.basemirror.project.name,
                                                          projectversion.basemirror.name,
                                                          projectversion.project.name,
                                                          projectversion.name)
                for dist in ["stable", "unstable"]:
                    snapshot_name = "{}-{}-".format(publish_name, dist)
                    if aptly_snapshot_name.startswith(snapshot_name):
                        task_id = await aptly.snapshot_delete(aptly_snapshot_name)
                        await aptly.wait_task(task_id)
                        # FIXME: delete task

            found = False
            for a in aptly_repos:
                if a.get("Name") == repo_name:
                    found = True
                    break
            if not found:
                continue
            logger.warning("renaming repo %s" % repo_name)
            try:
                task_id = await aptly.repo_rename(repo_name, repo_name + "-stable")
                await aptly.wait_task(task_id)
                # FIXME: delete task
                task_id = await aptly.repo_create(repo_name + "-unstable")
                await aptly.wait_task(task_id)
                # FIXME: delete task
            except Exception as exc:
                logger.exception(exc)


async def startup_mirror(task_queue):
    """
    Starts a finalize_mirror task in the asyncio event loop
    for all mirrors which have the state 'updating'
    """
    loop = asyncio.get_event_loop()
    aptly = get_aptly_connection()

    with Session() as session:
        # get mirrors in updating state
        query = session.query(ProjectVersion)
        query = query.join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(True))
        query = query.filter(or_(ProjectVersion.mirror_state == "updating",
                                 ProjectVersion.mirror_state == "publishing",
                                 ProjectVersion.mirror_state == "error"))

        if not query.count():
            return

        mirrors = query.all()
        tasks = await aptly.get_tasks()

        for mirror in mirrors:
            base_mirror = ""
            base_mirror_version = ""
            tasknames = ["Update mirror", "Publish snapshot:"]

            m_tasks = None
            build_state = None
            mirror_state = None
            if tasks:
                for i in range(len(tasknames)):
                    taskname = tasknames[i]
                    if not mirror.project.is_basemirror:
                        base_mirror = mirror.basemirror.project.name
                        base_mirror_version = mirror.basemirror.name
                        task_name = "{} {}-{}-{}-{}-".format(taskname, base_mirror, base_mirror_version,
                                                             mirror.project.name, mirror.name)
                    else:
                        task_name = "{} {}-{}-".format(taskname, mirror.project.name, mirror.name)
                    # FIXME: search for each component
                    #  "Publish snapshot: buster-10.4-cmps-main, buster-10.4-cmps-non-free",

                    tmp_tasks = [task for task in tasks if task["Name"].startswith(task_name)]
                    if tmp_tasks:
                        m_tasks = tmp_tasks
                        if i == 0:
                            build_state = "building"
                            mirror_state = "updating"
                        elif i == 1:
                            build_state = "publishing"
                            mirror_state = "publishing"
                        # do not break here, use last task in the list

            if not m_tasks:
                # No task on aptly found
                logger.info("no mirroring tasks found on aptly")
                mirror.mirror_state = "error"
                session.commit()
                continue

            m_task = max(m_tasks, key=operator.itemgetter("ID"))

            build = (
                session.query(Build)
                .filter(
                    Build.buildtype == "mirror",
                    Build.projectversion_id == mirror.id,
                )
                .first()
            )
            if not build:
                logger.info("no build found for mirror")
                mirror.mirror_state = "error"
                session.commit()
                continue

            # FIXME: do not allow db cleanup while mirroring

            mirror.mirror_state = mirror_state
            build.buildstate = build_state
            session.commit()

            await write_log(build.id, "W: continuing active mirroring\n")

            components = mirror.mirror_components.split(",")
            loop.create_task(
                finalize_mirror(
                    task_queue,
                    build.id,
                    base_mirror,
                    base_mirror_version,
                    mirror.project.name,
                    mirror.name,
                    components,
                    # FIXME: add all running tasks
                    [m_task.get("ID")],
                )
            )


async def update_mirror(task_queue, build_id, base_mirror, base_mirror_version, mirror, version, components):
    """
    Creates an update task in the asyncio event loop.

    Args:
        mirror (str): The mirror's name (project name).
        version (str): The mirror's version.
        base_distribution (str): The mirror's base dist (mirror_distribution).
        components (list): The mirror's components
    """

    aptly = get_aptly_connection()
    # FIXME: do not allow db cleanup while mirroring
    task_ids = await aptly.mirror_update(base_mirror, base_mirror_version, mirror, version, components)

    logger.debug("start update progress: aptly tasks %s", str(task_ids))
    loop = asyncio.get_event_loop()
    loop.create_task(finalize_mirror(task_queue, build_id, base_mirror, base_mirror_version,
                                     mirror, version, components, task_ids))


async def finalize_mirror(task_queue, build_id, base_mirror, base_mirror_version,
                          mirror_project, mirror_version, components, task_ids):
    try:
        mirrorname = "{}-{}".format(mirror_project, mirror_version)
        logger.debug("finalizing mirror %s tasks %s, build_%d", mirrorname, str(task_ids), build_id)

        with Session() as session:

            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: mirror build with id %d not found", build_id)
                return

            # FIXME: get mirror from build.projectversion_id
            query = session.query(ProjectVersion)
            query = query.join(Project, Project.id == ProjectVersion.project_id)
            query = query.filter(Project.is_mirror.is_(True))
            query = query.filter(ProjectVersion.name == mirror_version)
            mirror = query.filter(Project.name == mirror_project).first()

            if not mirror:
                logger.error("finalize mirror: mirror '%s' not found", mirrorname)
                await write_log(build.id, "E: error mirror not found\n")
                return

            aptly = get_aptly_connection()

            progress = {}
            for task_id in task_ids:
                progress[task_id] = {}
                progress[task_id]["State"] = 1  # set running

            fields = ["TotalNumberOfPackages", "RemainingNumberOfPackages",
                      "TotalDownloadSize", "RemainingDownloadSize"]

            if mirror.mirror_state == "updating":
                while True:
                    for task_id in task_ids:
                        if progress[task_id]["State"] == 1:  # task is running
                            upd_progress = await aptly.mirror_get_progress(task_id)
                            if upd_progress:
                                progress[task_id].update(upd_progress)
                            else:
                                progress[task_id]["State"] = 3  # mark failed

                    # check if at least 1 is running
                    # 0: init, 1: running, 2: success, 3: failed
                    running = False
                    failed = False
                    for task_id in task_ids:
                        if progress[task_id]["State"] == 1:
                            running = True
                        if progress[task_id]["State"] == 3:
                            failed = True

                    if not running and failed:
                        logger.error("Error updating mirror %s", mirrorname)
                        await write_log(build.id, "E: error updating mirror\n")
                        mirror.mirror_state = "error"
                        await build.set_failed()
                        session.commit()
                        # FIXME: delete all tasks
                        # await aptly.delete_task(task_id)
                        return

                    if not running and not failed:
                        break

                    total_progress = {}
                    for field in fields:
                        total_progress[field] = 0

                    if running:
                        for task_id in task_ids:
                            for field in fields:
                                if field in progress[task_id]:
                                    total_progress[field] += progress[task_id][field]

                        if total_progress["TotalNumberOfPackages"] > 0:
                            total_progress["PercentPackages"] = (
                                (total_progress["TotalNumberOfPackages"] - total_progress["RemainingNumberOfPackages"])
                                / total_progress["TotalNumberOfPackages"] * 100.0)
                        else:
                            total_progress["PercentPackages"] = 0.0

                        if "TotalDownloadSize" in total_progress and total_progress["TotalDownloadSize"] > 0:
                            total_progress["PercentSize"] = (
                                (total_progress["TotalDownloadSize"] - total_progress["RemainingDownloadSize"])
                                / total_progress["TotalDownloadSize"] * 100.0)
                        else:
                            total_progress["PercentSize"] = 0.0

                        logger.info("mirrored %d/%d files (%.02f%%), %.02f/%.02fGB (%.02f%%)",
                                    total_progress["TotalNumberOfPackages"] - total_progress["RemainingNumberOfPackages"],
                                    total_progress["TotalNumberOfPackages"], total_progress["PercentPackages"],
                                    (total_progress["TotalDownloadSize"] - total_progress["RemainingDownloadSize"])
                                    / 1024.0 / 1024.0 / 1024.0,
                                    total_progress["TotalDownloadSize"] / 1024.0 / 1024.0 / 1024.0,
                                    total_progress["PercentSize"],
                                    )

                        await notify(Subject.build.value, Event.changed.value,
                                     {"id": build.id, "progress": total_progress["PercentSize"]})
                        await notify(Subject.mirror.value, Event.changed.value,
                                     {"id": mirror.id, "progress": total_progress["PercentSize"]})
                    await asyncio.sleep(10)

                await write_log(build.id, "I: creating snapshot\n")

                await build.set_publishing()
                session.commit()

                # snapshot after initial download
                logger.debug("creating snapshot for: %s", mirrorname)
                try:
                    task_ids = await aptly.mirror_snapshot(base_mirror, base_mirror_version,
                                                           mirror_project, mirror_version, components)
                except AptlyError as exc:
                    logger.error("error creating mirror %s snapshot: %s", mirrorname, exc)
                    mirror.mirror_state = "error"
                    await build.set_publish_failed()
                    session.commit()
                    return

                while True:
                    running = False
                    failed = False
                    for task_id in task_ids:
                        try:
                            task_state = await aptly.get_task_state(task_id)
                        except Exception:
                            failed = True

                        # 0: init, 1: running, 2: success, 3: failed
                        if task_state["State"] == 1:
                            running = True
                        if task_state["State"] == 3:
                            failed = True

                    if not running and failed:
                        logger.error("creating mirror %s snapshot failed", mirrorname)
                        mirror.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()
                        return
                    if not running and not failed:
                        break

                    await asyncio.sleep(2)

                # FIXME: delete all tasksk
                # await aptly.delete_task(task_id)

                mirror.mirror_state = "publishing"
                session.commit()

                # publish new snapshot
                await write_log(build.id, "I: publishing mirror\n")
                logger.debug("publishing snapshot: %s", mirrorname)
                try:
                    task_id = await aptly.mirror_publish(base_mirror, base_mirror_version, mirror_project, mirror_version,
                                                         mirror.mirror_distribution, components)
                except Exception as exc:
                    logger.error("error publishing mirror %s snapshot: %s", mirrorname, str(exc))
                    mirror.mirror_state = "error"
                    await build.set_publish_failed()
                    session.commit()
                    await aptly.mirror_delete(base_mirror, base_mirror_version, mirror_project, mirror_version,
                                              mirror.mirror_distribution, components)
                    return

            if mirror.mirror_state == "publishing":
                while True:
                    upd_progress = None
                    try:
                        upd_progress = await aptly.mirror_get_progress(task_id)
                    except Exception as exc:
                        logger.error("error publishing mirror %s: %s", mirrorname, str(exc))

                        mirror.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()

                        await aptly.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror_project, mirror_version)
                        return

                    # States:
                    # 0: init, 1: running, 2: success, 3: failed
                    if upd_progress["State"] == 2:
                        break
                    if upd_progress["State"] == 3:
                        logger.error("error publishing mirror %s snapshot", mirrorname)
                        mirror.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()
                        await aptly.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror_project, mirror_version)
                        return

                    if upd_progress["TotalNumberOfPackages"] > 0:
                        upd_progress["PercentPackages"] = (
                            (upd_progress["TotalNumberOfPackages"] - upd_progress["RemainingNumberOfPackages"])
                            / upd_progress["TotalNumberOfPackages"] * 100.0)
                    else:
                        upd_progress["PercentPackages"] = 0.0

                    if "TotalDownloadSize" in upd_progress and upd_progress["TotalDownloadSize"] > 0:
                        upd_progress["PercentSize"] = (
                            (upd_progress["TotalDownloadSize"] - upd_progress["RemainingDownloadSize"])
                            / upd_progress["TotalDownloadSize"] * 100.0)
                    else:
                        upd_progress["PercentSize"] = 0.0

                    logger.info("published %d/%d packages (%.02f%%)",
                                upd_progress["TotalNumberOfPackages"] - upd_progress["RemainingNumberOfPackages"],
                                upd_progress["TotalNumberOfPackages"], upd_progress["PercentPackages"])

                    await notify(Subject.build.value, Event.changed.value,
                                 {"id": build.id, "progress": upd_progress["PercentPackages"]})
                    await notify(Subject.mirror.value, Event.changed.value,
                                 {"id": mirror.id, "progress": upd_progress["PercentPackages"]})
                    await asyncio.sleep(10)

            if mirror.project.is_basemirror:
                await create_chroots(mirror, build, mirror_project, mirror_version, task_queue, session)

            mirror.is_locked = True
            mirror.mirror_state = "ready"
            session.commit()

            await build.set_successful()
            session.commit()

            await write_log(build_id, "\n")
            await write_log_title(build_id, "Done", no_footer_newline=True)
            logger.debug("mirror %s succesfully created", mirrorname)

    except Exception as exc:
        logger.exception(exc)


async def create_chroots(mirror, build, mirror_project, mirror_version, task_queue, session):
    for arch_name in db2array(mirror.mirror_architectures):
        await write_log(build.id, "I: starting chroot environments build\n")

        chroot_build = Build(
            version=mirror_version,
            git_ref=None,
            ci_branch=None,
            is_ci=None,
            sourcename=mirror_project,
            buildstate="new",
            buildtype="chroot",
            projectversion_id=build.projectversion_id,
            parent_id=build.id,
            sourcerepository=None,
            maintainer=None,
            architecture=arch_name
        )

        session.add(chroot_build)
        session.commit()
        chroot_build.log_state("created")
        await chroot_build.build_added()

        await chroot_build.set_needs_build()
        session.commit()

        await chroot_build.set_scheduled()
        session.commit()

        chroot = Chroot(basemirror_id=mirror.id, architecture=arch_name, build_id=chroot_build.id, ready=False)
        session.add(chroot)
        session.commit()

        # create chroot build envs
        args = {"buildenv": [
                chroot.id,
                chroot_build.id,
                mirror.mirror_distribution,
                mirror.project.name,
                mirror.name,
                arch_name,
                mirror.mirror_components,
                chroot.get_mirror_url(),
                chroot.get_mirror_keys(),
                ]}
        await task_queue.put(args)


class AptlyWorker:
    """
    Source Packaging worker thread

    """

    def __init__(self, aptly_queue, task_queue):
        self.aptly_queue = aptly_queue
        self.task_queue = task_queue

    async def _create_mirror(self, args, session):
        (
            mirror_name,
            url,
            mirror_distribution,
            components,
            keys,
            keyserver,
            is_basemirror,
            architectures,
            mirror_version,
            key_url,
            basemirror_id,
            download_sources,
            download_installer,
            external_repo
        ) = args

        # FIXME: the following db checking should happen in api
        mirror_project = session.query(Project).filter(Project.name == mirror_name, Project.is_mirror.is_(True)).first()
        if not mirror_project:
            mirror_project = Project(name=mirror_name, is_mirror=True, is_basemirror=is_basemirror)
            session.add(mirror_project)

        project_version = (
            session.query(ProjectVersion)
            .join(Project)
            .filter(Project.name == mirror_name, Project.is_mirror.is_(True))
            .filter(ProjectVersion.name == mirror_version)
            .first()
        )

        if project_version:
            logger.error("mirror with name '%s' and version '%s' already exists", mirror_name, mirror_version)
            return

        # FIXME: check basemirror exists
        # FIXME: until here, should be in api

        mirror = ProjectVersion(
            name=mirror_version,
            project=mirror_project,
            mirror_url=url,
            mirror_distribution=mirror_distribution,
            mirror_components=",".join(components),
            mirror_architectures=array2db(architectures),
            mirror_with_sources=download_sources,
            mirror_with_installer=download_installer,
            mirror_state="new",
            basemirror_id=basemirror_id,
            external_repo=external_repo
        )

        session.add(mirror)
        session.commit()

        mirrorkey = MirrorKey(
                projectversion_id=mirror.id,
                keyurl=key_url,
                keyids=array2db(keys),
                keyserver=keyserver)

        session.add(mirrorkey)

        build = Build(
            version=mirror_version,
            git_ref=None,
            ci_branch=None,
            is_ci=False,
            sourcename=mirror_name,
            buildstate="new",
            buildtype="mirror",
            sourcerepository=None,
            maintainer=None,
            projectversion_id=mirror.id
        )

        session.add(build)
        session.commit()
        build.log_state("created")
        await build.build_added()

        args = {"init_mirror": [mirror.id]}
        await self.aptly_queue.put(args)
        return True

    async def _init_mirror(self, args, session):
        mirror_id = args[0]
        mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
        if not mirror:
            logger.error("aptly worker: mirror with id %d not found", mirror_id)
            return

        build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
        if not build:
            logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
            return

        await write_log_title(build.id, "Create Mirror")

        mirrorkey = session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
        if mirrorkey:
            key_url = mirrorkey.keyurl
            keyids = db2array(mirrorkey.keyids)
            keyserver = mirrorkey.keyserver

        if not mirror.external_repo:
            aptly = get_aptly_connection()
            if key_url:
                await write_log(build.id, "I: adding GPG keys from {}\n".format(key_url))
                try:
                    await aptly.gpg_add_key(key_url=key_url)
                except AptlyError as exc:
                    await write_log(build.id, "E: Error adding keys from '%s'\n" % key_url)
                    logger.error("key error: %s", exc)
                    await build.set_failed()
                    mirror.mirror_state = "init_error"
                    session.commit()
                    return False
            elif keyserver and keyids:
                await write_log(build.id, "I: adding GPG keys {} from {}\n".format(keyids, keyserver))
                try:
                    await aptly.gpg_add_key(key_server=keyserver, keys=keyids)
                except AptlyError as exc:
                    await write_log(build.id, "E: Error adding keys %s\n" % str(keyids))
                    logger.error("key error: %s", exc)
                    await build.set_failed()
                    mirror.mirror_state = "init_error"
                    session.commit()
                    return False

            await write_log(build.id, "I: creating mirror\n")
            try:
                await aptly.mirror_create(
                    mirror.project.name,
                    mirror.name,
                    mirror.basemirror.project.name if mirror.basemirror else "",
                    mirror.basemirror.name if mirror.basemirror else "",
                    mirror.mirror_url,
                    mirror.mirror_distribution,
                    mirror.mirror_components.split(" "),
                    db2array(mirror.mirror_architectures),
                    download_sources=mirror.mirror_with_sources,
                    download_udebs=mirror.mirror_with_installer,
                    download_installer=mirror.mirror_with_installer,
                )

            except NotFoundError as exc:
                await write_log(build.id, "E: aptly seems to be not available: %s\n" % str(exc))
                logger.error("aptly seems to be not available: %s", str(exc))
                await build.set_failed()
                mirror.mirror_state = "init_error"
                session.commit()
                return False

            except AptlyError as exc:
                await write_log(build.id, "E: failed to create mirror %s on aptly: %s\n" % (mirror, str(exc)))
                logger.error("failed to create mirror %s on aptly: %s", mirror, str(exc))
                await build.set_failed()
                mirror.mirror_state = "init_error"
                session.commit()
                return False

        mirror.mirror_state = "created"
        session.commit()

        args = {"update_mirror": [mirror.id]}
        await self.aptly_queue.put(args)
        return True

    async def _update_mirror(self, args, session):
        mirror_id = args[0]
        mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
        if not mirror:
            logger.error("aptly worker: mirror with id %d not found", mirror_id)
            return

        build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
        if not build:
            logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
            return

        await write_log(build.id, "I: updating mirror\n")

        mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
        if not mirror:
            await write_log(build.id, "E: aptly worker: mirror with id %d not found\n" % mirror_id)
            logger.error("aptly worker: mirror with id %d not found", mirror_id)
            return

        build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
        if not build:
            await write_log(build.id, "E: aptly worker: no build found for mirror with id %d\n" % str(mirror_id))
            logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
            return

        if not mirror.external_repo:
            await build.set_building()
            session.commit()

            mirror_name = "{}/{}".format(mirror.project.name, mirror.name)
            try:
                await update_mirror(
                    self.task_queue,
                    build.id,
                    mirror.basemirror.project.name if mirror.basemirror else "",
                    mirror.basemirror.name if mirror.basemirror else "",
                    mirror.project.name,
                    mirror.name,
                    mirror.mirror_components.split(","),
                )
            except NotFoundError as exc:
                await write_log(build.id, "E: aptly seems to be not available: %s\n" % str(exc))
                logger.error("aptly seems to be not available: %s", str(exc))
                # FIXME: remove from db
                await build.set_failed()
                session.commit()
                return
            except AptlyError as exc:
                await write_log(build.id, "E: failed to update mirror %s on aptly: %s\n" % (mirror_name, str(exc)))
                logger.error("failed to update mirror %s on aptly: %s", mirror_name, str(exc))
                # FIXME: remove from db
                await build.set_failed()
                session.commit()
                return

            mirror.mirror_state = "updating"
            session.commit()

        else:  # external repo
            if mirror.project.is_basemirror:
                await create_chroots(mirror, build, mirror.project.name, mirror.name, self.task_queue, session)

            mirror.is_locked = True
            mirror.mirror_state = "ready"
            session.commit()

            await build.set_successful()
            session.commit()

            await write_log(build.id, "\n")
            await write_log_title(build.id, "Done", no_footer_newline=True)

    async def _src_publish(self, args, session):
        build_id = args[0]

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("aptly worker: build with id %d not found", build_id)
            return

        await build.set_publishing()
        session.commit()

        ret = False
        try:
            ret = await DebSrcPublish(session, build)
        except Exception as exc:
            logger.exception(exc)

        if not ret:
            await write_log(build.parent.id, "E: publishing source package failed\n")
            await write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)
            await build.set_publish_failed()
            session.commit()
            return

        await build.set_successful()
        session.commit()

        await write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)

        await write_log(build.parent.id, "I: scheduling deb package builds\n")
        # schedule child builds
        childs = session.query(Build).filter(Build.parent_id == build.id).all()
        if not childs:
            logger.error("publishsrc_succeeded no build childs found for %d", build_id)
            await write_log(build.parent.id, "E: no deb builds found\n")
            await write_log_title(build.parent.id, "Done", no_footer_newline=True, no_header_newline=True)
            await build.parent.set_failed()
            session.commit()
            return

        for child in childs:
            await child.set_needs_build()
            session.commit()

        # Schedule builds
        args = {"schedule": []}
        await self.task_queue.put(args)

    async def _publish(self, args, session):
        build_id = args[0]
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("aptly worker: build with id %d not found", build_id)
            return

        await build.set_needs_publish()
        await build.set_publishing()
        session.commit()

        ret = False
        try:
            ret = await DebPublish(session, build)
        except Exception as exc:
            logger.exception(exc)

        if ret:
            await build.set_successful()
        else:
            await build.set_publish_failed()
            await write_log(build.parent.parent.id, "E: publishing build %d failed\n" % build.id)
            await write_log(build.parent.id, "E: publishing build failed\n")
            await write_log(build.id, "E: publishing build failed\n")
        await write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=False)
        session.commit()

        if not build.is_ci:
            send_mail_notification(build)

        # Schedule builds
        args = {"schedule": []}
        await self.task_queue.put(args)

    async def _drop_publish(self, args, _):
        base_mirror_name = args[0]
        base_mirror_version = args[1]
        projectname = args[2]
        projectversion = args[3]
        dist = args[4]

        aptly = get_aptly_connection()
        await aptly.publish_drop(base_mirror_name, base_mirror_version, projectname, projectversion, dist)

    async def _init_repository(self, args, session):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version, architectures).init()

    async def _snapshot_repository(self, args, session):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        snapshot_name = args[5]
        packages = args[6]
        await DebianRepository(basemirror_name, basemirror_version, project_name,
                               project_version, architectures).snapshot(snapshot_name, packages)

    async def _delete_repository(self, args, session):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version, architectures).delete()

    async def _cleanup(self, args, session):
        logger.info("aptly worker: running cleanup")
        aptly = get_aptly_connection()
        await aptly.cleanup()

    async def _delete_mirror(self, args, session):
        mirror_id = args[0]
        mirror = session.query(ProjectVersion).join(Project).filter(ProjectVersion.id == mirror_id,
                                                                    Project.is_mirror.is_(True)).first()
        if not mirror:
            logger.error("aptly worker: mirror with id %d not found", mirror_id)
            return

        aptly = get_aptly_connection()

        base_mirror = ""
        base_mirror_version = ""
        if not mirror.project.is_basemirror:
            base_mirror = mirror.basemirror.project.name
            base_mirror_version = mirror.basemirror.name
            # FIXME: cleanup chroot table, schroots, debootstrap,

        try:
            # FIXME: use altpy queue !
            await aptly.mirror_delete(base_mirror, base_mirror_version, mirror.project.name,
                                      mirror.name, mirror.mirror_distribution, mirror.mirror_components.split(","))
        except Exception as exc:
            # mirror did not exist
            # FIXME: handle mirror has snapshots and cannot be deleted?
            logger.exception(exc)

        # remember for later
        project = mirror.project

        if mirror.project.is_basemirror:
            chroots = session.query(Chroot).filter(Chroot.basemirror_id == mirror.id).all()
            for chroot in chroots:
                session.delete(chroot)
                # FIXME: delete files

        # FIXME: should this be Build.basemirror_id ?
        builds = session.query(Build) .filter(Build.projectversion_id == mirror.id).all()
        for build in builds:
            # FIXME: remove buildout dir / debootstrap
            session.delete(build)

        mirrorkey = session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
        if mirrorkey:
            session.delete(mirrorkey)
        session.commit()

        session.delete(mirror)
        session.commit()

        # delete parent project if no mirror versions left
        if not project.projectversions:
            session.delete(project)

        session.commit()

    async def run(self):
        """
        Run the worker task.
        """

        await startup_mirror(self.task_queue)
        await startup_migration(self.task_queue)

        while True:
            try:
                task = await self.aptly_queue.get()
                if task is None:
                    logger.error("aptly worker: got emtpy task, aborting...")
                    break

                with Session() as session:

                    handled = False
                    if not handled:
                        args = task.get("src_publish")
                        if args:
                            handled = True
                            await self._src_publish(args, session)

                    if not handled:
                        args = task.get("publish")
                        if args:
                            handled = True
                            await self._publish(args, session)

                    if not handled:
                        args = task.get("create_mirror")
                        if args:
                            handled = True
                            await self._create_mirror(args, session)

                    if not handled:
                        args = task.get("init_mirror")
                        if args:
                            handled = True
                            await self._init_mirror(args, session)

                    if not handled:
                        args = task.get("update_mirror")
                        if args:
                            handled = True
                            await self._update_mirror(args, session)

                    if not handled:
                        args = task.get("drop_publish")
                        if args:
                            handled = True
                            await self._drop_publish(args, session)

                    if not handled:
                        args = task.get("init_repository")
                        if args:
                            handled = True
                            await self._init_repository(args, session)

                    if not handled:
                        args = task.get("snapshot_repository")
                        if args:
                            handled = True
                            await self._snapshot_repository(args, session)

                    if not handled:
                        args = task.get("delete_repository")
                        if args:
                            handled = True
                            await self._delete_repository(args, session)

                    if not handled:
                        args = task.get("delete_mirror")
                        if args:
                            handled = True
                            await self._delete_mirror(args, session)

                    if not handled:
                        args = task.get("cleanup")
                        # FIXME: check args is []
                        # FIXME: postpone if mirroring is active
                        handled = True
                        await self._cleanup(args, session)

                    if not handled:
                        logger.error("aptly worker got unknown task %s", str(task))

                    self.aptly_queue.task_done()

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating aptly worker task")
