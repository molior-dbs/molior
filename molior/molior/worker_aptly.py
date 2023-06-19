import asyncio
import operator

from os import mkdir
from shutil import rmtree
from sqlalchemy import func, or_
from shutil import copy2

from ..app import logger
from ..tools import db2array, array2db
from ..ops import DebSrcPublish, DebPublish, DeleteBuildEnv
from ..aptly import get_aptly_connection
from ..aptly.errors import AptlyError, NotFoundError
from .debianrepository import DebianRepository
from .notifier import Subject, Event, notify, send_mail_notification
from ..molior.queues import enqueue_task, enqueue_aptly, dequeue_aptly, buildlog, buildlogtitle, buildlogdone, enqueue_backend
from ..molior.configuration import Configuration

from ..model.database import Session
from ..model.build import Build
from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_projectversion_byid
from ..model.chroot import Chroot
from ..model.mirrorkey import MirrorKey


def mirror_architectures(mirror):
    '''Return the mirror architectures to use on aptly for a given mirror.
    Add "source" as architecture when updating mirror on aptly to trigger source downloading/snapshotting/publishing.
    '''
    mirror_architectures = db2array(mirror.mirror_architectures)
    if mirror.mirror_with_sources:
        mirror_architectures.append('source')
    return mirror_architectures


async def startup_mirror():
    """
    Starts a finalize_mirror task in the asyncio event loop
    for all mirrors which have the state 'updating'
    """
    loop = asyncio.get_event_loop()
    aptly = get_aptly_connection()
    tasks = await aptly.get_tasks()

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

            build = session.query(Build).filter(Build.buildtype == "mirror", Build.projectversion_id == mirror.id).first()
            if not build:
                logger.info("no build found for mirror")
                mirror.mirror_state = "error"
                session.commit()
                continue

            # FIXME: do not allow db cleanup while mirroring

            mirror.mirror_state = mirror_state
            build.buildstate = build_state
            session.commit()

            await build.log("W: continuing active mirroring\n")

            components = mirror.mirror_components.split(",")
            loop.create_task(
                finalize_mirror(
                    build.id,
                    base_mirror,
                    base_mirror_version,
                    mirror.project.name,
                    mirror.name,
                    components,
                    mirror_architectures(mirror),
                    # FIXME: add all running tasks
                    [m_task.get("ID")],
                )
            )


async def update_mirror(build_id, base_mirror, base_mirror_version, mirror, version, components, architectures):
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
    loop.create_task(finalize_mirror(build_id, base_mirror, base_mirror_version,
                                     mirror, version, components, architectures, task_ids))


async def finalize_mirror(build_id, base_mirror, base_mirror_version,
                          mirror_project, mirror_version, components, architectures, task_ids):
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
            query = query.filter(func.lower(ProjectVersion.name) == mirror_version.lower())
            mirror = query.filter(func.lower(Project.name) == mirror_project.lower()).first()

            if not mirror:
                logger.error("finalize mirror: mirror '%s' not found", mirrorname)
                await build.log("E: error mirror not found\n")
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
                        await build.log("E: error updating mirror\n")
                        mirror.mirror_state = "error"
                        await build.set_failed()
                        await build.logdone()
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
                    await asyncio.sleep(5)

                await build.log("I: creating snapshot\n")

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
                await build.log("I: publishing mirror\n")
                logger.debug("publishing snapshot: %s", mirrorname)
                try:
                    task_id = await aptly.mirror_publish(base_mirror, base_mirror_version, mirror_project, mirror_version,
                                                         mirror.mirror_distribution, components, architectures)
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

                        await aptly.mirror_snapshot_delete(base_mirror, base_mirror_version,
                                                           mirror_project, mirror_version, components)
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
                        await aptly.mirror_snapshot_delete(base_mirror, base_mirror_version,
                                                           mirror_project, mirror_version, components)
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
                    await asyncio.sleep(5)

            if mirror.project.is_basemirror:
                await create_chroots(mirror, build, mirror_project, mirror_version, session)

            mirror.is_locked = True
            mirror.mirror_state = "ready"
            session.commit()

            await build.set_successful()
            session.commit()

            await build.log("\n")
            await build.logtitle("Done", no_footer_newline=True)
            await build.logdone()
            logger.debug("mirror %s succesfully created", mirrorname)

    except Exception as exc:
        logger.exception(exc)


async def create_chroots(mirror, build, mirror_project, mirror_version, session):
    for arch_name in db2array(mirror.mirror_architectures):
        await build.log("I: starting chroot environments build\n")

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
        await enqueue_task(args)


class AptlyWorker:
    """
    Aptly worker thread

    """

    async def _init_mirror(self, args):
        mirror_id = args[0]

        with Session() as session:
            mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
            if not mirror:
                logger.error("aptly worker: mirror with id %d not found", mirror_id)
                return False

            build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
            if not build:
                logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
                return False

            await build.logtitle("Create Mirror")

            mirrorkey = session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
            if mirrorkey:
                key_url = mirrorkey.keyurl
                keyids = db2array(mirrorkey.keyids)
                keyserver = mirrorkey.keyserver

            if not mirror.external_repo:
                aptly = get_aptly_connection()
                if key_url:
                    await build.log("I: adding GPG keys from {}\n".format(key_url))
                    try:
                        await aptly.gpg_add_key(key_url=key_url)
                    except AptlyError as exc:
                        await build.log("E: Error adding keys from '%s'\n" % key_url)
                        logger.error("key error: %s", exc)
                        await build.set_failed()
                        await build.logdone()
                        mirror.mirror_state = "init_error"
                        session.commit()
                        return False
                elif keyserver and keyids:
                    await build.log("I: adding GPG keys {} from {}\n".format(keyids, keyserver))
                    try:
                        await aptly.gpg_add_key(key_server=keyserver, keys=keyids)
                    except AptlyError as exc:
                        await build.log("E: Error adding keys %s\n" % str(keyids))
                        logger.error("key error: %s", exc)
                        await build.set_failed()
                        await build.logdone()
                        mirror.mirror_state = "init_error"
                        session.commit()
                        return False

                await build.log("I: creating mirror\n")
                if mirror.mirror_filter:
                    await build.log("I: using filter %s\n" % mirror.mirror_filter)
                try:
                    await aptly.mirror_create(
                        mirror.project.name,
                        mirror.name,
                        mirror.basemirror.project.name if mirror.basemirror else "",
                        mirror.basemirror.name if mirror.basemirror else "",
                        mirror.mirror_url,
                        mirror.mirror_distribution,
                        # FIXME: should be array in db
                        # NOTE: return empty array when the components are empty, because
                        # the default `.split()` algorythm returns `[""]` when
                        # an empty string is given: https://stackoverflow.com/a/16645307/12356463
                        mirror.mirror_components.split(",") if mirror.mirror_components else [],
                        db2array(mirror.mirror_architectures),
                        mirror.mirror_filter,
                        download_sources=mirror.mirror_with_sources,
                        download_udebs=mirror.mirror_with_installer,
                        download_installer=mirror.mirror_with_installer,
                    )

                except NotFoundError as exc:
                    await build.log("E: aptly seems to be not available: %s\n" % str(exc))
                    logger.error("aptly seems to be not available: %s", str(exc))
                    await build.set_failed()
                    await build.logdone()
                    mirror.mirror_state = "init_error"
                    session.commit()
                    return False

                except AptlyError as exc:
                    await build.log("E: failed to create mirror %s on aptly: %s\n" % (mirror, str(exc)))
                    logger.error("failed to create mirror %s on aptly: %s", mirror, str(exc))
                    await build.set_failed()
                    await build.logdone()
                    mirror.mirror_state = "init_error"
                    session.commit()
                    return False

            mirror.mirror_state = "created"
            session.commit()

        args = {"update_mirror": [mirror_id]}
        await enqueue_aptly(args)
        return True

    async def _update_mirror(self, args):
        mirror_id = args[0]

        with Session() as session:

            build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
            if not build:
                await build.log("E: aptly worker: no build found for mirror with id %d\n" % str(mirror_id))
                logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
                return

            mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
            if not mirror:
                await build.log("E: aptly worker: mirror with id %d not found\n" % mirror_id)
                logger.error("aptly worker: mirror with id %d not found", mirror_id)
                return

            # FIXME add timestamp
            await build.log("I: updating mirror\n")

            if not mirror.external_repo:
                await build.set_building()
                session.commit()

                mirror_name = "{}/{}".format(mirror.project.name, mirror.name)
                try:
                    await update_mirror(
                        build.id,
                        mirror.basemirror.project.name if mirror.basemirror else "",
                        mirror.basemirror.name if mirror.basemirror else "",
                        mirror.project.name,
                        mirror.name,
                        mirror.mirror_components.split(","),
                        mirror_architectures(mirror)
                    )
                except NotFoundError as exc:
                    await build.log("E: aptly seems to be not available: %s\n" % str(exc))
                    logger.error("aptly seems to be not available: %s", str(exc))
                    # FIXME: remove from db
                    await build.set_failed()
                    await build.logdone()
                    session.commit()
                    return
                except AptlyError as exc:
                    await build.log("E: failed to update mirror %s on aptly: %s\n" % (mirror_name, str(exc)))
                    logger.error("failed to update mirror %s on aptly: %s", mirror_name, str(exc))
                    # FIXME: remove from db
                    await build.set_failed()
                    await build.logdone()
                    session.commit()
                    return

                mirror.mirror_state = "updating"
                session.commit()

            else:  # external repo
                if mirror.project.is_basemirror:
                    await create_chroots(mirror, build, mirror.project.name, mirror.name, session)

                mirror.is_locked = True
                mirror.mirror_state = "ready"
                session.commit()

                await build.set_successful()
                session.commit()

                await build.log("\n")
                await build.logtitle("Done", no_footer_newline=True)
                await build.logdone()

    async def _src_publish(self, args):
        build_id = args[0]

        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return False

            await build.set_publishing()
            session.commit()
            repo_id = build.sourcerepository_id
            sourcename = build.sourcename
            version = build.version
            projectversions = build.projectversions
            is_ci = build.is_ci
            parent_id = build.parent_id

        ret = False
        try:
            ret = await DebSrcPublish(build_id, repo_id, sourcename, version, projectversions, is_ci)
        except Exception as exc:
            logger.exception(exc)

        if not ret:  # src publish failed, no more logs for parent
            await buildlogtitle(parent_id, "Done", no_footer_newline=True, no_header_newline=True)
            await buildlogdone(parent_id)

        await buildlogtitle(build_id, "Done", no_footer_newline=True, no_header_newline=True)
        await buildlogdone(build_id)

        found_childs = False
        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return False
            if not ret:
                await build.set_publish_failed()
                session.commit()
                return False

            # publish succeded
            await build.set_successful()
            session.commit()

            # schedule child builds
            childs = session.query(Build).filter(Build.parent_id == build.id).all()
            if not childs:
                logger.error("publishsrc_succeeded no build childs found for %d", build_id)
                await build.parent.set_failed()
                session.commit()

            for child in childs:
                found_childs = True
                await child.set_needs_build()
                session.commit()

        if not found_childs:
            await buildlog(parent_id, "E: no deb builds found\n")
            await buildlogtitle(parent_id, "Done", no_footer_newline=True, no_header_newline=True)
            await buildlogdone(parent_id)
            return False

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)
        return True

    async def _publish(self, args):
        build_id = args[0]

        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return

            await build.set_publishing()
            session.commit()

            basemirror_name = build.projectversion.basemirror.project.name
            basemirror_version = build.projectversion.basemirror.name
            project_name = build.projectversion.project.name
            project_version = build.projectversion.name
            archs = db2array(build.projectversion.mirror_architectures)
            parent_parent_id = build.parent.parent.id
            buildtype = build.buildtype
            sourcename = build.sourcename
            version = build.version
            architecture = build.architecture
            is_ci = build.is_ci

        await buildlog(parent_parent_id, "I: publishing debian packages for %s\n" % architecture)

        ret = False
        try:
            ret = await DebPublish(build_id, buildtype, sourcename, version, architecture, is_ci,
                                   basemirror_name, basemirror_version, project_name, project_version, archs)
        except Exception as exc:
            logger.exception(exc)

        if not ret:
            await buildlog(parent_parent_id, "E: publishing build %d failed\n" % build.id)
            await buildlog(build_id, "E: publishing build failed\n")

        await buildlogtitle(build_id, "Done", no_footer_newline=True, no_header_newline=False)
        await buildlogdone(build_id)

        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return
            if ret:
                await build.set_successful()
            else:
                await build.set_publish_failed()
            session.commit()

            if not build.is_ci:
                send_mail_notification(build)

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)

    async def _drop_publish(self, args):
        base_mirror_name = args[0]
        base_mirror_version = args[1]
        projectname = args[2]
        projectversion = args[3]
        dist = args[4]

        aptly = get_aptly_connection()
        await aptly.publish_drop(base_mirror_name, base_mirror_version, projectname, projectversion, dist)

    async def _init_repository(self, args):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        trigger_builds = args[5]
        build_id = None
        if len(args) > 6:
            build_id = args[6]  # build id for copying projectversions

        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version, architectures).init()

        if build_id:
            with Session() as session:
                build = session.query(Build).filter(Build.id == build_id).first()
                if build:
                    await build.set_successful()
                    session.commit()

        if len(trigger_builds) > 0:
            targets = [f"{project_name}/{project_version}"]
            with Session() as session:
                builds = session.query(Build).filter(Build.id.in_(trigger_builds)).all()
                for build in builds:
                    args = {"build": [build.id, build.sourcerepository_id, f"v{build.version}", "", targets, False]}
                    await enqueue_task(args)

    async def _snapshot_repository(self, args):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        snapshot_name = args[5]
        new_projectversion_id = args[6]
        latest_debbuilds_ids = args[7]
        packages = []
        copybuilds = []
        buildlogs = []
        with Session() as session:
            builds = session.query(Build).filter(Build.id.in_(latest_debbuilds_ids)).all()

            pkgbuilds = []
            for build in builds:
                copybuilds.append(build)
                pkgbuilds.append(build)
                if build.parent not in pkgbuilds:  # add source package
                    pkgbuilds.append(build.parent)

            for build in pkgbuilds:
                for deb in build.debianpackages:
                    arch = deb.suffix
                    if build.buildtype == "source":
                        arch = "source"
                    packages.append((deb.name, build.version, arch))

            # copy builds
            srcpackages = {}
            toppackages = {}

            def copybuild(build, parent_build_id):
                copy = Build(
                    version=build.version,
                    git_ref=build.git_ref,
                    ci_branch=build.ci_branch,
                    is_ci=build.is_ci,
                    sourcename=build.sourcename,
                    buildstate=build.buildstate,
                    buildtype=build.buildtype,
                    parent_id=parent_build_id,
                    sourcerepository_id=build.sourcerepository_id,
                    maintainer_id=build.maintainer_id,
                    architecture=build.architecture,
                    createdstamp=build.createdstamp,
                    startstamp=build.startstamp,
                    buildendstamp=build.buildendstamp,
                    endstamp=build.endstamp,
                    snapshotbuild_id=build.id,
                    debianpackages=build.debianpackages
                )
                if copy.buildtype == "deb":
                    copy.projectversion_id = new_projectversion_id
                if copy.buildtype == "source":
                    copy.projectversions = array2db([str(new_projectversion_id)])
                session.add(copy)
                session.commit()
                return copy

            for build in copybuilds:
                if build.parent.id not in srcpackages.values():
                    if build.parent.parent.id not in toppackages.values():
                        # create new top build
                        newbuild = copybuild(build.parent.parent, None)
                        toppackages[build.parent.parent.id] = newbuild.id
                        buildlogs.append((build.parent.parent.id, newbuild.id))

                    # create new src build
                    newbuild = copybuild(build.parent, toppackages[build.parent.parent_id])
                    srcpackages[build.parent.id] = newbuild.id
                    buildlogs.append((build.parent.id, newbuild.id))
                newbuild = copybuild(build, srcpackages[build.parent_id])
                buildlogs.append((build.id, newbuild.id))

        await DebianRepository(basemirror_name, basemirror_version, project_name,
                               project_version, architectures).snapshot(snapshot_name, packages)

        # copy build logs
        buildout_path = Configuration().working_dir + "/buildout"
        for old, new in buildlogs:
            try:
                mkdir(buildout_path + "/%d" % new)
                copy2(buildout_path + "/%d/build.log" % old, buildout_path + "/%d/build.log" % new)
            except Exception as exc:
                logger.exception(exc)

    async def _delete_repository(self, args):
        basemirror_name = args[0]
        basemirror_version = args[1]
        project_name = args[2]
        project_version = args[3]
        architectures = args[4]
        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version, architectures).delete()

    async def _cleanup(self, args):
        logger.info("aptly worker: running cleanup")
        with Session() as session:
            mirrors = session.query(ProjectVersion).join(Project).filter(Project.is_mirror).all()
            for mirror in mirrors:
                if mirror.mirror_state in ["updating", "publishing"]:
                    # FIXME: postpone if mirroring is active
                    logger.error("aptly cleanup: cannot start, mirroring is active for mirror with id %d", mirror.id)
                    return
        aptly = get_aptly_connection()
        await aptly.cleanup()

    async def _delete_mirror(self, args):
        mirror_id = args[0]
        aptly = get_aptly_connection()

        base_mirror = ""
        base_mirror_version = ""
        is_basemirror = False
        with Session() as session:
            mirror = session.query(ProjectVersion).join(Project).filter(ProjectVersion.id == mirror_id,
                                                                        Project.is_mirror.is_(True)).first()
            if not mirror:
                logger.error("aptly worker: mirror with id %d not found", mirror_id)
                return

            if not mirror.project.is_basemirror:
                base_mirror = mirror.basemirror.project.name
                base_mirror_version = mirror.basemirror.name

            is_basemirror = mirror.project.is_basemirror
            mirror_name = mirror.project.name
            mirror_version = mirror.name
            mirror_architectures = mirror.mirror_architectures
            mirror_distribution = mirror.mirror_distribution
            mirror_components = mirror.mirror_components.split(",")

        try:
            # FIXME: use altpy queue !
            await aptly.mirror_delete(base_mirror, base_mirror_version, mirror_name,
                                      mirror_version, mirror_distribution, mirror_components)
        except Exception as exc:
            # mirror did not exist
            # FIXME: handle mirror has snapshots and cannot be deleted?
            logger.exception(exc)

        archs = db2array(mirror_architectures)
        for arch in archs:
            try:
                await DeleteBuildEnv(mirror_distribution, mirror_name, mirror_version, arch)
            except Exception as exc:
                logger.exception(exc)

        with Session() as session:
            mirror = session.query(ProjectVersion).join(Project).filter(ProjectVersion.id == mirror_id,
                                                                        Project.is_mirror.is_(True)).first()
            if not mirror:
                logger.error("aptly worker: mirror with id %d not found", mirror_id)
                return

            # remember for later
            project = mirror.project

            if is_basemirror:
                chroots = session.query(Chroot).filter(Chroot.basemirror_id == mirror.id).all()
                for chroot in chroots:
                    session.delete(chroot)

            # FIXME: should this be Build.basemirror_id ?
            builds = session.query(Build) .filter(Build.projectversion_id == mirror.id).all()
            for build in builds:
                # FIXME: remove buildout dir
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

    async def _delete_build(self, args):
        build_id = args[0]
        logger.info("aptly worker: deleting build %d" % build_id)

        build_ids = [build_id]
        to_delete = {}
        publish_names = []
        with Session() as session:
            topbuild = session.query(Build).filter(Build.id == build_id).first()
            if not topbuild:
                logger.error("aptly worker: build %d not found" % build_id)
                return

            dist = "stable"
            if topbuild.is_ci:
                dist = "unstable"

            srcpkgs = []
            debpkgs = []
            for src in topbuild.children:
                build_ids.append(src.id)
                srcpkgs.append(src)
                for deb in src.children:
                    build_ids.append(deb.id)
                    debpkgs.append(deb)

            projectversions = {}
            for src in srcpkgs:
                if src.projectversions is None or len(src.projectversions) == 0:
                    continue
                if src.buildstate != "successful":
                    continue
                for f in src.debianpackages:
                    for projectversion_id in src.projectversions:
                        projectversion = get_projectversion_byid(projectversion_id, session)
                        if not projectversion:
                            logger.error("delete build: projectversion %d not found" % projectversion_id)
                            continue

                        # FIXME: only delete srcpkg if no other same build (repo, version, projectversion) has
                        # successful build in different arch

                        repo_name = "%s-%s-%s-%s-%s" % (projectversion.basemirror.project.name, projectversion.basemirror.name,
                                                        projectversion.project.name, projectversion.name, dist)
                        publish_name = "{}_{}_repos_{}_{}".format(projectversion.basemirror.project.name,
                                                                  projectversion.basemirror.name, projectversion.project.name,
                                                                  projectversion.name)
                        if projectversion_id not in projectversions:
                            projectversions[projectversion_id] = (repo_name, publish_name)
                        if publish_name not in publish_names:
                            publish_names.append(publish_name)
                        if repo_name not in to_delete:
                            to_delete[repo_name] = []
                        to_delete[repo_name].append((f.name, src.version, "source"))

            for deb in debpkgs:
                if deb.buildstate != "successful":  # only successful deb builds have packages to delete
                    continue
                for f in deb.debianpackages:
                    projectversion = deb.projectversion
                    repo_name = "%s-%s-%s-%s-%s" % (projectversion.basemirror.project.name, projectversion.basemirror.name,
                                                    projectversion.project.name, projectversion.name, dist)
                    if repo_name not in to_delete:
                        to_delete[repo_name] = []
                    to_delete[repo_name].append((f.name, deb.version, f.suffix))

        aptly = get_aptly_connection()
        aptly_delete = {}
        for repo_name in to_delete:
            for package in to_delete[repo_name]:
                # logger.error("delete %s %s" % (repo_name, pkgname))
                pkgs = await aptly.repo_packages_get(repo_name, "%s (= %s) {%s}" % (package[0],   # package name
                                                                                    package[1],   # version
                                                                                    package[2]))  # arch
                if repo_name not in aptly_delete:
                    aptly_delete[repo_name] = []
                aptly_delete[repo_name].extend(pkgs)

        for repo_name in aptly_delete:
            task_id = await aptly.repo_packages_delete(repo_name, aptly_delete[repo_name])
            await aptly.wait_task(task_id)

        for pv in projectversions:
            await aptly.republish(dist, projectversions[pv][0], projectversions[pv][1])

        for bid in build_ids:
            buildout = "/var/lib/molior/buildout/%d" % bid
            try:
                rmtree(buildout)
            except Exception:
                pass

        with Session() as session:
            top = session.query(Build).filter(Build.id == build_id).first()
            if not top:
                logger.error("aptly worker: build %d not found" % build_id)
                return

            to_delete = []
            for src in top.children:
                for deb in src.children:
                    to_delete.append(deb)
                to_delete.append(src)
            to_delete.append(top)

            for build in to_delete:
                build.debianpackages = []
                if build.buildtask:
                    session.delete(build.buildtask)
                session.delete(build)
            session.commit()

        logger.info("aptly worker: build %d deleted" % build_id)

    async def _abort(self, args):
        logger.debug("worker: got abort build task")
        build_id = args[0]

        with Session() as session:
            topbuild = session.query(Build).filter(Build.id == build_id).first()
            if not topbuild:
                logger.error("aptly worker: build %d not found" % build_id)
                return

            if len(topbuild.children) != 1:
                logger.error("aptly worker: no source build found for %d" % build_id)
                return

            await buildlog(build_id, "E: aborting build on user request\n")

            for deb in topbuild.children[0].children:
                # abort on build node
                if deb.buildstate in ["building", "scheduled"]:
                    await enqueue_backend({"abort": deb.id})

                if deb.buildstate in ["new", "needs_build", "scheduled"]:
                    await deb.set_failed()

                if deb.buildtask:
                    session.delete(deb.buildtask)

            await topbuild.set_failed()
            session.commit()

    async def run(self):
        """
        Run the worker task.
        """

        try:
            await startup_mirror()
        except Exception:
            pass

        while True:
            try:
                task = await dequeue_aptly()
                if task is None:
                    break

                handled = False
                if not handled:
                    args = task.get("src_publish")
                    if args:
                        handled = True
                        await self._src_publish(args)

                if not handled:
                    args = task.get("publish")
                    if args:
                        handled = True
                        await self._publish(args)

                if not handled:
                    args = task.get("init_mirror")
                    if args:
                        handled = True
                        await self._init_mirror(args)

                if not handled:
                    args = task.get("update_mirror")
                    if args:
                        handled = True
                        await self._update_mirror(args)

                if not handled:
                    args = task.get("drop_publish")
                    if args:
                        handled = True
                        await self._drop_publish(args)

                if not handled:
                    args = task.get("init_repository")
                    if args:
                        handled = True
                        await self._init_repository(args)

                if not handled:
                    args = task.get("snapshot_repository")
                    if args:
                        handled = True
                        await self._snapshot_repository(args)

                if not handled:
                    args = task.get("delete_repository")
                    if args:
                        handled = True
                        await self._delete_repository(args)

                if not handled:
                    args = task.get("delete_mirror")
                    if args:
                        handled = True
                        await self._delete_mirror(args)

                if not handled:
                    args = task.get("delete_build")
                    if args:
                        handled = True
                        await self._delete_build(args)

                if not handled:
                    args = task.get("abort")
                    if args:
                        handled = True
                        await self._abort(args)

                # must be last
                if not handled:
                    args = task.get("cleanup")
                    # FIXME: check args is []
                    handled = True
                    await self._cleanup(args)

                if not handled:
                    logger.error("aptly worker got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("aptly task terminated")
