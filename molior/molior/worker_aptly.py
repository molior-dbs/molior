import asyncio
import operator
from datetime import datetime

from os import mkdir
from shutil import rmtree
from shutil import copy2
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import func, or_, desc, text

from ..logger import logger
from ..tools import db2array, array2db
from ..ops import DebSrcPublish, DebPublish, DeleteBuildEnv
from ..aptly import AptlyApi, TaskState, get_aptly_connection, get_snapshot_name
from ..aptly.errors import AptlyError, NotFoundError
from .debianrepository import DebianRepository
from .notifier import Subject, Event, notify
from ..molior.queues import enqueue_task, enqueue_aptly, dequeue_aptly, buildlog, buildlogtitle, buildlogdone, enqueue_backend
from ..molior.configuration import Configuration

from ..model.database import Session
from ..model.build import Build
from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_projectversion_byid
from ..model.chroot import Chroot
from ..model.mirrorkey import MirrorKey
from ..model.buildtask import BuildTask
from ..model.sourepprover import SouRepProVer
from ..model.metadata import MetaData


# startup_mirror: aptly may start after molior
STARTUP_APTLY_ATTEMPTS = 6
STARTUP_APTLY_WAIT = 10


def mirror_architectures(mirror):
    '''Return the mirror architectures to use on aptly for a given mirror.
    Add "source" as architecture when updating mirror on aptly to trigger source downloading/snapshotting/publishing.
    '''
    mirror_architectures = db2array(mirror.mirror_architectures)
    if mirror.mirror_with_sources:
        mirror_architectures.append('source')
    return mirror_architectures


def mirror_aptly_names(base_mirror, base_mirror_version, mirror, version, components):
    '''Return the aptly names of a mirror: one per component ("trixie-13.8-main"), or one for a flat mirror.
    The aptly mirrors and their snapshots have these names.
    '''
    name, _ = AptlyApi.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)
    components = [c for c in components if c]
    if not components:
        return [name]
    return [f"{name}-{component}" for component in components]


async def create_aptly_mirror(aptly, mirror):
    '''Create the aptly mirrors (one per component) of a mirror from its settings in the DB.
    The ones that exist already on aptly are kept (not changed).

    Returns:
        tuple: (names of the aptly mirrors created, names of the ones that existed already)
    '''
    # FIXME: should be array in db
    # NOTE: return empty array when the components are empty, because
    # the default `.split()` algorythm returns `[""]` when
    # an empty string is given: https://stackoverflow.com/a/16645307/12356463
    components = mirror.mirror_components.split(",") if mirror.mirror_components else []
    base_mirror = mirror.basemirror.project.name if mirror.basemirror else ""
    base_mirror_version = mirror.basemirror.name if mirror.basemirror else ""
    created = await aptly.mirror_create(
        mirror.project.name,
        mirror.name,
        base_mirror,
        base_mirror_version,
        mirror.mirror_url,
        mirror.mirror_distribution,
        components,
        db2array(mirror.mirror_architectures),
        mirror.mirror_filter,
        download_sources=mirror.mirror_with_sources,
        download_udebs=mirror.mirror_with_installer,
        download_installer=mirror.mirror_with_installer,
        filter_with_deps=bool(mirror.mirror_filter_with_deps),
        skip_existing=True,
    )
    names = mirror_aptly_names(base_mirror, base_mirror_version, mirror.project.name, mirror.name, components)
    return created, [name for name in names if name not in created]


def is_mirror_publish_task(task_name, names):
    '''Is the aptly task the publish of the snapshots `names` (one per component, as mirror_publish() creates them)?

    aptly 1.6 names it 'Publish snapshot repository <prefix>/<distribution> with components "main", "contrib"
    and sources "<mirror>-main", "<mirror>-contrib"'. The sources part names the snapshots, which have the names
    of the aptly mirrors. "Publish snapshot: <names>" is also accepted (older format).
    '''
    if task_name == "Publish snapshot: " + ", ".join(names):
        return True
    sources = " and sources " + ", ".join(f'"{name}"' for name in names)
    return task_name.startswith("Publish snapshot repository ") and task_name.endswith(sources)


def mirror_resume_state(tasks, names):
    '''Decide how to continue a mirror after a molior restart, from the aptly task list.

    Args:
        tasks (list): aptly tasks (GET /api/tasks), dicts with "ID", "Name" and "State".
        names (list): aptly names of the mirror, see mirror_aptly_names().

    Returns:
        ("updating", ids): the update tasks of the latest update run, one per component, in any state.
            finalize_mirror() follows all of them and then snapshots and publishes.
        ("publishing", [id]): the latest publish task, if it is newer than the update tasks.
        (None, []): no task of this mirror on aptly.
    '''
    updates = {}
    for task in tasks:
        for name in names:
            if task["Name"] == f"Update mirror {name}":
                # a mirror updated twice: keep the latest task per component
                if name not in updates or task["ID"] > updates[name]["ID"]:
                    updates[name] = task

    publishes = [task for task in tasks if is_mirror_publish_task(task["Name"], names)]

    last_update = max([t["ID"] for t in updates.values()], default=-1)
    if publishes:
        publish = max(publishes, key=operator.itemgetter("ID"))
        if publish["ID"] > last_update:
            return "publishing", [publish["ID"]]

    if updates:
        return "updating", sorted(t["ID"] for t in updates.values())

    return None, []


def mirror_pending_tasks(tasks, names):
    '''Return the ids of aptly tasks still queued or running on the mirror (e.g. a snapshot or delete queued
    before a molior restart). aptly runs tasks on the same mirror one after the other.
    '''
    pending = (TaskState.INIT.value, TaskState.RUNNING.value)
    return sorted(task["ID"] for task in tasks
                  if task.get("State") in pending and any(task["Name"].endswith(f" {name}") for name in names))


async def startup_mirror():
    """
    Continues the mirrors after a molior restart: starts a finalize_mirror task for each mirror (state updating,
    publishing or error) whose update or publish tasks are still on aptly (aptly keeps running when molior restarts).

    Mirror builds left in building or publishing without tasks on aptly are failed here (cleanup_builds()
    skips mirror builds, so that a running mirror is not failed at startup).
    """
    loop = asyncio.get_event_loop()
    aptly = get_aptly_connection()

    tasks = None
    for attempt in range(STARTUP_APTLY_ATTEMPTS):
        try:
            tasks = await aptly.get_tasks() or []
            break
        except Exception as exc:
            logger.warning("startup mirror: aptly tasks not available (%s), attempt %d/%d",
                           exc, attempt + 1, STARTUP_APTLY_ATTEMPTS)
            await asyncio.sleep(STARTUP_APTLY_WAIT)
    if tasks is None:
        logger.error("startup mirror: aptly not available, running mirrors are not continued")
        tasks = []

    pending = (TaskState.INIT.value, TaskState.RUNNING.value)
    continued = []
    with Session() as session:
        query = session.query(ProjectVersion)
        query = query.join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(True))
        query = query.filter(or_(ProjectVersion.mirror_state == "updating",
                                 ProjectVersion.mirror_state == "publishing",
                                 ProjectVersion.mirror_state == "error"))
        mirrors = query.all()

        for mirror in mirrors:
            base_mirror = ""
            base_mirror_version = ""
            if not mirror.project.is_basemirror:
                base_mirror = mirror.basemirror.project.name
                base_mirror_version = mirror.basemirror.name
            components = mirror.mirror_components.split(",")
            mirrorname = "{}-{}".format(mirror.project.name, mirror.name)

            names = mirror_aptly_names(base_mirror, base_mirror_version, mirror.project.name, mirror.name, components)
            mirror_state, task_ids = mirror_resume_state(tasks, names)

            if not mirror_state:
                # No task on aptly found
                if mirror.mirror_state != "error":
                    logger.info("no mirroring tasks found on aptly for %s", mirrorname)
                    await mirror.set_mirror_state("error")
                    session.commit()
                continue

            if mirror.mirror_state == "error" and not any(
                    task["ID"] in task_ids and task.get("State") in pending for task in tasks):
                # the error is final: its tasks ended (e.g. published, then a build environment failed).
                # Continuing it would publish again; a retry or an update by the admin starts it again
                continue

            build = session.query(Build).filter(Build.buildtype == "mirror", Build.projectversion_id == mirror.id).first()
            if not build:
                logger.info("no build found for mirror %s", mirrorname)
                await mirror.set_mirror_state("error")
                session.commit()
                continue

            logger.info("mirror %s: continuing %s, aptly tasks %s", mirrorname, mirror_state, task_ids)

            # FIXME: do not allow db cleanup while mirroring

            await mirror.set_mirror_state(mirror_state)
            if mirror_state == "updating":
                await build.set_building()
            else:
                await build.set_publishing()
            session.commit()
            continued.append(build.id)

            await build.log("W: continuing active mirroring\n")

            loop.create_task(
                finalize_mirror(
                    build.id,
                    base_mirror,
                    base_mirror_version,
                    mirror.project.name,
                    mirror.name,
                    components,
                    mirror_architectures(mirror),
                    task_ids,
                )
            )

        # mirror builds interrupted by the restart, with nothing left on aptly
        builds = session.query(Build).filter(Build.buildtype == "mirror",
                                             Build.buildstate.in_(["building", "publishing"])).all()
        for build in builds:
            if build.id in continued:
                continue
            logger.warning("startup mirror: build %d was %s, no aptly task left", build.id, build.buildstate)
            await build.log("E: mirroring interrupted by a molior restart, no task left on aptly\n")
            if build.buildstate == "publishing":
                await build.set_publish_failed()
            else:
                await build.set_failed()
            await build.logdone()
            session.commit()


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

    # snapshots left from an earlier (failed) run would hide the new download, finalize_mirror() reuses existing ones
    for name in mirror_aptly_names(base_mirror, base_mirror_version, mirror, version, components):
        try:
            if await aptly.snapshot_exists(name):
                task = await aptly.DELETE(f"/snapshots/{name}")
                await aptly.wait_task(task["ID"])
        except Exception as exc:
            logger.warning("mirror update: could not delete old snapshot %s: %s", name, exc)

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

            # The download can take many hours, the publish too: do not keep a transaction (and its connection)
            # open while waiting for aptly. A connection would be lost when postgres restarts, and an open
            # transaction holds back vacuum. After a commit the objects are loaded again on the next access,
            # with a new connection from the pool (pool_pre_ping).
            mirror_id = mirror.id
            mirror_state = mirror.mirror_state
            session.commit()

            if mirror_state == "updating":
                while True:
                    # 0: init (queued on aptly), 1: running, 2: success, 3: failed
                    # after a restart some tasks may be done already, others still queued: poll until done
                    pending = (TaskState.INIT.value, TaskState.RUNNING.value)
                    for task_id in task_ids:
                        if progress[task_id]["State"] in pending:
                            upd_progress = await aptly.mirror_get_progress(task_id)
                            if upd_progress:
                                progress[task_id].update(upd_progress)
                            else:
                                progress[task_id]["State"] = 3  # mark failed

                    # check if at least 1 is queued or running
                    running = False
                    failed = False
                    for task_id in task_ids:
                        if progress[task_id]["State"] in pending:
                            running = True
                        if progress[task_id]["State"] == 3:
                            failed = True

                    if not running and failed:
                        logger.error("Error updating mirror %s", mirrorname)
                        await build.log("E: error updating mirror\n")
                        await mirror.set_mirror_state("error")
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
                                     {"id": build_id, "progress": total_progress["PercentSize"]})
                        await notify(Subject.mirror.value, Event.changed.value,
                                     {"id": mirror_id, "progress": total_progress["PercentSize"]})
                    await asyncio.sleep(5)

                await build.log("I: creating snapshot\n")

                await build.set_publishing()
                session.commit()

                # snapshot after initial download
                logger.debug("creating snapshot for: %s", mirrorname)
                names = mirror_aptly_names(base_mirror, base_mirror_version, mirror_project, mirror_version, components)
                try:
                    # tasks queued on this mirror before a molior restart (e.g. a snapshot) run first on aptly
                    while mirror_pending_tasks(await aptly.get_tasks() or [], names):
                        await asyncio.sleep(5)

                    # a snapshot made after the download (e.g. queued before a restart) is used as is
                    missing = [component for component, name in zip(components, names)
                               if not await aptly.snapshot_exists(name)]
                    if missing:
                        task_ids = await aptly.mirror_snapshot(base_mirror, base_mirror_version,
                                                               mirror_project, mirror_version, missing)
                    else:
                        task_ids = []
                except AptlyError as exc:
                    logger.error("error creating mirror %s snapshot: %s", mirrorname, exc)
                    await mirror.set_mirror_state("error")
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
                            continue

                        # 0: init (queued on aptly), 1: running, 2: success, 3: failed
                        if task_state["State"] in (TaskState.INIT.value, TaskState.RUNNING.value):
                            running = True
                        if task_state["State"] == 3:
                            failed = True

                    if not running and failed:
                        logger.error("creating mirror %s snapshot failed", mirrorname)
                        await mirror.set_mirror_state("error")
                        await build.set_publish_failed()
                        session.commit()
                        return
                    if not running and not failed:
                        break

                    await asyncio.sleep(2)

                # FIXME: delete all tasksk
                # await aptly.delete_task(task_id)

                await mirror.set_mirror_state("publishing")
                session.commit()

                # publish new snapshot
                await build.log("I: publishing mirror\n")
                logger.debug("publishing snapshot: %s", mirrorname)
                try:
                    task_id = await aptly.mirror_publish(base_mirror, base_mirror_version, mirror_project, mirror_version,
                                                         mirror.mirror_distribution, components, architectures,
                                                         mirror.mirror_slash_workaround)
                except Exception as exc:
                    # keep the aptly mirror and its snapshots: the download may be hundreds of GB
                    logger.error("error publishing mirror %s snapshot: %s", mirrorname, str(exc))
                    await build.log("E: error publishing mirror: {}\n".format(exc))
                    await mirror.set_mirror_state("error")
                    await build.set_publish_failed()
                    await build.logdone()
                    session.commit()
                    return

                mirror_state = "publishing"
                session.commit()  # no transaction open while waiting for the publish

            elif mirror_state == "publishing":
                task_id = task_ids[0]  # continued after a restart: the publish task found by startup_mirror

            if mirror_state == "publishing":
                while True:
                    upd_progress = None
                    try:
                        upd_progress = await aptly.mirror_get_progress(task_id)
                    except Exception as exc:
                        logger.error("error publishing mirror %s: %s", mirrorname, str(exc))

                        await build.log("E: error publishing mirror: {}\n".format(exc))
                        await mirror.set_mirror_state("error")
                        await build.set_publish_failed()
                        await build.logdone()
                        session.commit()
                        # keep the snapshots: they may be published already (aptly refuses to drop those)
                        return

                    # States:
                    # 0: init, 1: running, 2: success, 3: failed
                    if upd_progress["State"] == 2:
                        break
                    if upd_progress["State"] == 3:
                        logger.error("error publishing mirror %s snapshot", mirrorname)
                        await build.log("E: error publishing mirror (aptly task %d failed)\n" % task_id)
                        await mirror.set_mirror_state("error")
                        await build.set_publish_failed()
                        await build.logdone()
                        session.commit()
                        # keep the snapshots: they may be published already (aptly refuses to drop those)
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
                                 {"id": build_id, "progress": upd_progress["PercentPackages"]})
                    await notify(Subject.mirror.value, Event.changed.value,
                                 {"id": mirror_id, "progress": upd_progress["PercentPackages"]})
                    await asyncio.sleep(5)

            if mirror.project.is_basemirror:
                await create_chroots(mirror, build, mirror_project, mirror_version, session)
            else:
                await build.set_successful()
                mirror.is_locked = True
                await mirror.set_mirror_state("ready")
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


async def retention_cleanup(session, build):

    # the number of successful builds to retain per sourcerepository
    max_successful_versions = build.projectversion.retention_successful_builds

    # no cleanup_needed
    if not max_successful_versions:
        return [], []

    # how many successful builds are for the sourcerepository
    past_debbuilds = session.query(Build).filter(
        Build.buildstate == "successful",
        Build.buildtype == "deb",
        Build.version != build.version,
        Build.is_ci.is_(False),
        Build.sourcename == build.sourcename,
        # different source repositories can build the same source name (None: uploaded builds)
        Build.sourcerepository_id == build.sourcerepository_id,
        Build.projectversion_id == build.projectversion_id).order_by(desc(Build.id)).all()
    past_versions = []
    for debbuild in past_debbuilds:
        if debbuild.version not in past_versions:
            past_versions.append(debbuild.version)

    # count the current build as successful
    version_count = len(past_versions) + 1
    if version_count < max_successful_versions:
        return [], []

    # how many builds should be deleted
    delete_count = version_count - max_successful_versions
    if delete_count > 10:
        delete_count = 10
        logger.warning("deleting maximum of 10 successful_builds")
    versions_to_delete = past_versions[-delete_count:]

    debpkgs = []
    for debbuild in past_debbuilds:
        if debbuild.version in versions_to_delete:
            debpkgs.append(debbuild)

    await buildlog(build.parent.parent.id, "I: there is a total of %d build(s) that exceed the amount of retention \n"
                   % delete_count)

    remove_packages = []
    remove_build_ids = []
    srcpkgs = []
    for debbuild_to_delete in debpkgs:
        remove_build_ids.append(debbuild_to_delete.id)
        # if the source package has no other deb packages, delete it and the toplevel package
        if len(debbuild_to_delete.parent.children) == 1:
            srcpkgs.append(debbuild_to_delete.parent)
            remove_build_ids.append(debbuild_to_delete.parent.id)
            remove_build_ids.append(debbuild_to_delete.parent.parent.id)

    for src in srcpkgs:
        for f in src.debianpackages:
            remove_packages.append((f.name, src.version, "source"))

    for deb in debpkgs:
        for f in deb.debianpackages:
            remove_packages.append((f.name, deb.version, f.suffix))

    return remove_build_ids, remove_packages


class AptlyWorker:
    """
    Aptly worker thread

    """

    def __init__(self):
        self.threadexc = ThreadPoolExecutor(max_workers=5)
        # build logs closed during the current publish (the worker handles one task at a time)
        self._logs_done = set()

    async def _log_done(self, build_id, no_header_newline):
        """
        Writes the "Done" footer and closes the build log. The footer is written only once
        per publish, but the log is always closed (a message written to a closed log opens a new writer).
        """
        if build_id not in self._logs_done:
            self._logs_done.add(build_id)
            await buildlogtitle(build_id, "Done", no_footer_newline=True, no_header_newline=no_header_newline)
        await buildlogdone(build_id)

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

            await build.set_building()
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
                    ret = False
                    try:
                        ret, msg = await aptly.gpg_add_key(key_url=key_url)
                    except Exception as exc:
                        pass
                        msg = exc

                    if not ret:
                        await build.log(f"E: Error adding gpg keys: {msg}\n")
                        await build.set_failed()
                        await build.logdone()
                        await mirror.set_mirror_state("init_error")
                        session.commit()
                        return False
                    await build.log(f"  {msg}\n")
                elif keyserver and keyids:
                    await build.log("I: adding GPG keys {} from {}\n".format(keyids, keyserver))
                    ret, msg = await aptly.gpg_add_key(key_server=keyserver, keys=keyids)
                    if not ret:
                        await build.log("E: Error adding gpg keys\n{msg}\n")
                        await build.set_failed()
                        await build.logdone()
                        await mirror.set_mirror_state("init_error")
                        session.commit()
                        return False
                    await build.log(f"  {msg}\n")

                await build.log("I: creating mirror\n")
                if mirror.mirror_filter:
                    await build.log("I: using filter %s%s\n" % (mirror.mirror_filter,
                                    " (with dependencies)" if mirror.mirror_filter_with_deps else ""))
                try:
                    # skip existing: a retry after an init that created only some of the components
                    _, existing = await create_aptly_mirror(aptly, mirror)
                    if existing:
                        await build.log("I: mirror exists already on aptly: %s\n" % ", ".join(existing))

                except NotFoundError as exc:
                    await build.log("E: aptly seems to be not available: %s\n" % str(exc))
                    logger.error("aptly seems to be not available: %s", str(exc))
                    await build.set_failed()
                    await build.logdone()
                    await mirror.set_mirror_state("init_error")
                    session.commit()
                    return False

                except Exception as exc:
                    await build.log("E: failed to create mirror on aptly: %s\n" % str(exc))
                    logger.error("failed to create mirror on aptly: %s", str(exc))
                    await build.set_failed()
                    await build.logdone()
                    await mirror.set_mirror_state("init_error")
                    session.commit()
                    return False

            await mirror.set_mirror_state("created")
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
                    # an aptly mirror can be missing, e.g. deleted after a failed update: create it again
                    missing, _ = await create_aptly_mirror(get_aptly_connection(), mirror)
                    if missing:
                        await build.log("I: mirror missing on aptly, created again: %s\n" % ", ".join(missing))
                        logger.warning("update mirror %s: created missing aptly mirrors %s", mirror_name, missing)
                except Exception as exc:
                    await build.log("E: failed to create missing mirror %s on aptly: %s\n" % (mirror_name, str(exc)))
                    logger.error("failed to create missing mirror %s on aptly: %s", mirror_name, str(exc))
                    await mirror.set_mirror_state("error")
                    await build.set_failed()
                    await build.logdone()
                    session.commit()
                    return

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

                await mirror.set_mirror_state("updating")
                session.commit()

            else:  # external repo
                if mirror.project.is_basemirror:
                    await create_chroots(mirror, build, mirror.project.name, mirror.name, session)
                else:
                    mirror.is_locked = True
                    await mirror.set_mirror_state("ready")
                    await build.set_successful()
                    session.commit()

                await build.log("\n")
                await build.logtitle("Done", no_footer_newline=True)
                await build.logdone()

    async def _publish_error(self, build_id, exc):
        """
        Called when an exception escaped from _publish or _src_publish.
        Without it the build would stay in "publishing" (or "needs_publish") and all
        builds depending on it would wait for it until the next start of molior.
        """
        try:
            with Session() as session:
                build = session.query(Build).filter(Build.id == build_id).first()
                if not build:
                    return
                if build.buildstate not in ["needs_publish", "publishing"]:
                    return  # the build was already finished or aborted

                buildtype = build.buildtype
                parent_id = build.parent_id
                await buildlog(build_id, "E: internal error while publishing: %s\n" % repr(exc))
                await build.set_publish_failed()  # sets the top build to failed
                session.commit()

            await self._log_done(build_id, no_header_newline=(buildtype == "source"))
            if buildtype == "source":
                await self._log_done(parent_id, no_header_newline=True)
            else:
                await enqueue_task({"schedule": []})
        except Exception as exc2:
            logger.exception(exc2)

    async def _src_publish(self, args):
        self._logs_done = set()
        try:
            await self._do_src_publish(args)
        except Exception as exc:
            logger.exception(exc)
            await self._publish_error(args[0], exc)

    async def _do_src_publish(self, args):
        build_id = args[0]

        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return False

            if build.buildstate in ["build_failed", "publish_failed"]:
                logger.info("aptly worker: build %d was aborted, not publishing", build_id)
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
            await self._log_done(parent_id, no_header_newline=True)

        await self._log_done(build_id, no_header_newline=True)

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
            await self._log_done(parent_id, no_header_newline=True)
            return False

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)
        return True

    async def _publish(self, args):
        self._logs_done = set()
        try:
            await self._do_publish(args)
        except Exception as exc:
            logger.exception(exc)
            await self._publish_error(args[0], exc)

    async def _do_publish(self, args):
        build_id = args[0]

        # builds to delete from db and remove buildlogs
        builds_to_delete = []
        # remove src and deb packages from aptly
        remove_packages = []
        retention_error = None
        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return

            if build.buildstate in ["build_failed", "publish_failed"]:
                logger.info("aptly worker: build %d was aborted, not publishing", build_id)
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
            publish_s3 = None
            if build.projectversion and build.projectversion.publish_s3:
                s3_endpoint = build.projectversion.s3_endpoint
                s3_path = build.projectversion.s3_path
                publish_s3 = f"{s3_endpoint}:{s3_path.replace('/', '_')}"  # on aptly, directory separatos is _ for publishing

            if not is_ci:
                # Retention is housekeeping: an error must not fail the publish. Log it and
                # publish without removing anything, the next publish does the cleanup.
                try:
                    builds_to_delete, remove_packages = await retention_cleanup(session, build)
                except Exception as exc:
                    logger.exception(exc)
                    builds_to_delete, remove_packages = [], []
                    retention_error = repr(exc)

        if retention_error:
            await buildlog(build_id, "E: retention cleanup failed, obsolete packages are not removed: %s\n"
                           % retention_error)
        await buildlog(parent_parent_id, "I: publishing debian packages for %s\n" % architecture)

        ret = False
        try:
            ret = await DebPublish(build_id, buildtype, sourcename, version, architecture, is_ci,
                                   basemirror_name, basemirror_version, project_name, project_version,
                                   archs, remove_packages, publish_s3=publish_s3)
        except Exception as exc:
            logger.exception(exc)

        if not ret:
            await buildlog(parent_parent_id, "E: publishing build %d failed\n" % build_id)
            await buildlog(build_id, "E: publishing build failed\n")

        await self._log_done(build_id, no_header_newline=False)

        with Session() as session:
            # set current buildstate
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: build with id %d not found", build_id)
                return
            if ret:
                # remove buildout of obsolete builds
                def remove_buildout():
                    for del_id in builds_to_delete:
                        buildout = "/var/lib/molior/buildout/%d" % del_id
                        try:
                            rmtree(buildout)
                        except Exception:
                            pass
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(self.threadexc, remove_buildout)

                # remove obsolete builds from db
                for del_id in builds_to_delete:
                    del_build = session.query(Build).filter(Build.id == del_id).first()
                    if not del_build:
                        logger.warning("aptly worker: build with id %d not found", del_id)
                        continue
                    del_build.debianpackages = []
                    if del_build.buildtask:
                        session.delete(del_build.buildtask)
                    session.delete(del_build)

                await build.set_successful()
            else:
                await build.set_publish_failed()
            session.commit()

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)

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

        error = None
        try:
            if not await DebianRepository(
                    basemirror_name, basemirror_version, project_name, project_version, architectures).init():
                error = f"repository of {project_name}/{project_version} already exists"
        except Exception as exc:
            if not build_id:
                raise
            logger.exception(exc)
            error = str(exc)

        if build_id:
            with Session() as session:
                build = session.query(Build).filter(Build.id == build_id).first()
                if build:
                    if error:
                        logger.error("init repository %s/%s: %s", project_name, project_version, error)
                        await build.log(f"E: {error}\n")
                        await build.set_failed()
                        await build.logdone()
                    else:
                        await build.set_successful()
                    session.commit()
            if error:
                return

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

        def copy_buildout():
            # copy build logs
            buildout_path = Configuration().working_dir + "/buildout"
            for old, new in buildlogs:
                try:
                    mkdir(buildout_path + "/%d" % new)
                    copy2(buildout_path + "/%d/build.log" % old, buildout_path + "/%d/build.log" % new)
                except Exception as exc:
                    logger.exception(exc)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.threadexc, copy_buildout)

    async def _delete_repository(self, args):
        projectversion_id = args[0]
        delete_build_id = args[1]
        basemirror_name = None
        basemirror_version = None
        project_name = None
        project_version = None
        architectures = None
        publish_s3 = None

        build_ids = []
        with Session() as db:
            # remember configuration
            projectversion = get_projectversion_byid(projectversion_id, db)
            if not projectversion:
                logger.error("delete projectversion: projectversion %d not found" % projectversion_id)
                return

            basemirror_name = projectversion.basemirror.project.name
            basemirror_version = projectversion.basemirror.name
            project_name = projectversion.project.name
            project_version = projectversion.name
            architectures = db2array(projectversion.mirror_architectures)
            if projectversion.publish_s3:
                s3_endpoint = projectversion.s3_endpoint
                s3_path = projectversion.s3_path
                publish_s3 = f"{s3_endpoint}:{s3_path.replace('/', '_')}"  # on aptly, directory separatos is _ for publishing

            # delete deb builds and parents if needed
            todelete = []
            debbuilds = db.query(Build).filter(Build.projectversion_id == projectversion_id, Build.buildtype == "deb").all()
            for debbuild in debbuilds:
                todelete.append(debbuild)

            for debbuild in debbuilds:
                sourcebuild = None
                if debbuild.parent:
                    sourcebuild = debbuild.parent
                    for child in debbuild.parent.children:
                        if child.projectversion_id == projectversion_id:
                            continue
                        sourcebuild = None  # source build has childs belonging to a different projectversion
                if sourcebuild and sourcebuild not in todelete:
                    todelete.append(sourcebuild)

            def deletebuild(build):
                buildtasks = db.query(BuildTask).filter(BuildTask.build == build).all()
                for buildtask in buildtasks:
                    db.delete(buildtask)
                build_ids.append(build.id)
                db.delete(build)

            for build in todelete:
                if build.buildtype == "source":
                    topbuild = build.parent
                    deletebuild(build)
                    if topbuild:
                        deletebuild(topbuild)
                else:
                    deletebuild(build)

            # delete hooks
            todelete = []
            sourepovers = db.query(SouRepProVer).filter(SouRepProVer.projectversion_id == projectversion_id).all()
            for sourcerepositoryprojectversion in sourepovers:
                todelete.append(sourcerepositoryprojectversion)

            db.commit()

            for d in todelete:
                db.delete(d)

            # delete references from copies and snapshots
            relatives = db.query(ProjectVersion).filter(ProjectVersion.baseprojectversion_id == projectversion_id).all()
            for relative in relatives:
                relative.baseprojectversion_id = None

            db.commit()

            # delete projectversion
            db.delete(projectversion)
            db.commit()

        # move to model build
        def remove_buildout():
            for build_id in build_ids:
                buildout = "/var/lib/molior/buildout/%d" % build_id
                try:
                    rmtree(buildout)
                except Exception:
                    pass
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.threadexc, remove_buildout)

        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version,
                               architectures, publish_s3=publish_s3).delete()

        with Session() as db:
            build = db.query(Build).filter(Build.id == delete_build_id).first()
            if not build:
                logger.error("delete projectversion: build %d not found" % delete_build_id)
                return
            await build.set_successful()
            db.commit()

    async def _cleanup(self, args):
        logger.error("cleanup")

        # FIXME what are we doing with failed src/topbuild package builds
        # FIXME what about failed mirror builds
        logger.info("checking for obsolete builds")
        logger.info("in _scheduled_cleanupin worker_aptly")

        with Session() as session:
            mirrors = session.query(ProjectVersion).join(Project).filter(Project.is_mirror).all()
            for mirror in mirrors:
                if mirror.mirror_state in ["updating", "publishing"]:
                    # FIXME: postpone if mirroring is active
                    logger.error("aptly cleanup: cannot start, mirroring is active for mirror with id %d", mirror.id)
                    return

        with Session() as session:
            projectversions = session.query(ProjectVersion).join(Project).filter(
                Project.is_mirror.is_(False),
                ProjectVersion.is_locked.is_(False)
            ).order_by(ProjectVersion.id.desc()).all()

            # create cleanup build
            cleanup_build = Build(
                version=None,
                git_ref=None,
                ci_branch=None,
                is_ci=False,
                sourcename="Cleanup",
                buildstate="scheduled",
                buildtype="cleanup",
                sourcerepository=None,
                maintainer=None,
            )

            session.add(cleanup_build)
            await cleanup_build.logtitle("Cleanup")
            await cleanup_build.build_added()

            await cleanup_build.set_building()
            session.commit()

            cleanup_max = 100
            t = session.query(MetaData).filter_by(name="cleanup_max").first()
            if t:
                cleanup_max = int(t.value)

            builds_to_delete = []
            successful_builds_to_delete = []
            failed_builds_to_delete = []

            successful_complete = False
            failed_complete = False
            for projectversion in projectversions:
                if successful_complete and failed_complete:
                    break
                if not failed_complete:
                    failed_builds = session.query(Build).filter(
                        Build.projectversion_id == projectversion.id,
                        Build.buildtype == "deb",
                        ProjectVersion.retention_failed_builds <= func.extract('epoch', datetime.now() - Build.endstamp) / 86400,
                        or_(Build.buildstate == "build_failed",
                            Build.buildstate == "publish_failed",
                            )
                    ).order_by(Build.id.desc()).all()

                    logger.info("lenght of failed_builds: %d", len(failed_builds))

                    for build in failed_builds:
                        failed_builds_to_delete.append(build)
                        if len(failed_builds_to_delete) == cleanup_max:
                            failed_complete = True
                            break

                if not successful_complete:
                    successful_builds = session.query(Build).filter(
                        Build.projectversion_id == projectversion.id,
                        Build.buildtype == "deb",
                        Build.buildstate == "successful"
                    ).order_by(Build.id.desc()).all()

                    successful_delete_candidates = {}

                    for build in successful_builds:
                        if build.sourcename not in successful_delete_candidates:
                            successful_delete_candidates[build.sourcename] = []
                        successful_delete_candidates[build.sourcename].append(build)

                    # FIXME logic could be part of the sqlalchemy query
                    for sourcename in successful_delete_candidates:
                        if successful_complete:
                            break
                        amount_successful_builds = len(successful_delete_candidates[sourcename])
                        retention_successful_builds = projectversion.retention_successful_builds
                        amount_exceeded = amount_successful_builds - retention_successful_builds

                        if amount_exceeded > 0:
                            for build in successful_delete_candidates[sourcename][:-amount_exceeded]:
                                successful_builds_to_delete.append(build)
                                if len(successful_builds_to_delete) == cleanup_max:
                                    successful_complete = True
                                    break
            logger.info("length of failed builds: %d", len(failed_builds_to_delete))
            logger.info("length of succ builds: %d", len(successful_builds_to_delete))

            if len(failed_builds_to_delete) < cleanup_max:
                if len(successful_builds_to_delete) > 0:
                    builds_to_delete = failed_builds_to_delete + \
                                       successful_builds_to_delete[:-(cleanup_max-len(failed_builds_to_delete))]
                else:
                    builds_to_delete = failed_builds_to_delete
            elif len(successful_builds_to_delete) < cleanup_max:
                if len(failed_builds_to_delete) > 0:
                    builds_to_delete = successful_builds_to_delete + \
                                       failed_builds_to_delete[:-(cleanup_max-len(successful_builds_to_delete))]
                else:
                    builds_to_delete = successful_builds_to_delete
            else:
                if len(failed_builds_to_delete) > 0 and len(successful_builds_to_delete) > 0:
                    builds_to_delete = failed_builds_to_delete[:-int(len(failed_builds_to_delete)*0.5)] + \
                                       successful_builds_to_delete[:-int(len(successful_builds_to_delete)*0.5)]
                elif len(failed_builds_to_delete) > 0:
                    builds_to_delete = failed_builds_to_delete
                else:
                    builds_to_delete = successful_builds_to_delete

            i = 0
            logger.info("length of builds_to_delete: %d", len(builds_to_delete))
            for build in builds_to_delete:
                i += 1
                logger.info(f"deleting build {i} of {len(builds_to_delete)}")
                logger.info("build id: %d", build.id)
                logger.info("buildstate: %s", build.buildstate)

            cleanup_build_id = cleanup_build.id

            logger.info("cleanup_build_id: %s", cleanup_build_id)

            i = 0
            for build in builds_to_delete:
                i = i + 1

                await buildlog(cleanup_build_id, "I: deleting build %s of %s\n" % (i, cleanup_max))

                logger.info(f"deleting build {i} of {cleanup_max}")

                siblings = 0
                if build.parent:
                    siblings = len(build.parent.children)

                if siblings == 1:
                    sourcename = build.parent.parent.sourcename
                    start_stamp = build.parent.parent.startstamp
                    topbuild_id = build.parent.parent.id
                    logger.info(f"Sourcename: {sourcename}, Start stamp: {start_stamp}, Build ID: {topbuild_id}")
                    await buildlog(cleanup_build_id, "I: deleting debian, source and topbuild of %s-%s\n" % (sourcename,
                                   build.version))
                    await enqueue_aptly({"delete_build": [topbuild_id]})
                else:
                    sourcename = build.sourcename
                    start_stamp = build.startstamp
                    oldest_build_id = build.id
                    logger.info(f"Sourcename: {sourcename}, Start stamp: {start_stamp}, Build ID: {oldest_build_id}")
                    await buildlog(cleanup_build_id, "I: deleting debian package %s-%s\n" % (sourcename, build.version))
                    await enqueue_aptly({"delete_deb_build": [oldest_build_id]})

            logger.info("aptly worker: running weekly cleanup")

            aptly = get_aptly_connection()
            await aptly.cleanup()

            await cleanup_build.set_successful()
            session.commit()

        logger.info("end of cleanup function")

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
            mirror_slash_workaround = mirror.mirror_slash_workaround
            mirror_components = mirror.mirror_components.split(",") if mirror.mirror_components else []

        try:
            # FIXME: use altpy queue !
            await aptly.mirror_delete(base_mirror, base_mirror_version, mirror_name,
                                      mirror_version, mirror_distribution, mirror_components, mirror_slash_workaround)
        except Exception as exc:
            # mirror did not exist
            # FIXME: handle mirror has snapshots and cannot be deleted?
            logger.exception(exc)

        if is_basemirror:
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
                            publish_s3 = None
                            if projectversion.publish_s3:
                                s3_endpoint = projectversion.s3_endpoint
                                s3_path = projectversion.s3_path
                                # on aptly, directory separatos is _ for publishing
                                publish_s3 = f"{s3_endpoint}:{s3_path.replace('/', '_')}"
                            projectversions[projectversion_id] = (repo_name, publish_name,
                                                                  db2array(projectversion.mirror_architectures),
                                                                  publish_s3)
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
            logger.info("aptly_delete")
            logger.info(aptly_delete[repo_name])
            task_id = await aptly.repo_packages_delete(repo_name, aptly_delete[repo_name])
            await aptly.wait_task(task_id)

        for pv in projectversions:
            await aptly.republish(dist, projectversions[pv][2], projectversions[pv][0],
                                  projectversions[pv][1], publish_s3=projectversions[pv][3])

        def remove_buildout():
            for build_id in build_ids:
                buildout = "/var/lib/molior/buildout/%d" % build_id
                try:
                    rmtree(buildout)
                except Exception:
                    pass
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.threadexc, remove_buildout)

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

    async def _delete_deb_build(self, args):
        build_id = args[0]
        logger.info("aptly worker: deleting Debian packages for build %d" % build_id)

        build_ids = [build_id]
        to_delete = {}
        with Session() as session:
            topbuild = session.query(Build).filter(Build.id == build_id).first()
            if not topbuild:
                logger.error("aptly worker: build %d not found" % build_id)
                return

            dist = "stable"
            if topbuild.is_ci:
                dist = "unstable"

            debpkgs = []
            for src in topbuild.children:
                for deb in src.children:
                    build_ids.append(deb.id)
                    debpkgs.append(deb)

            projectversions = {}
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
            logger.info("REPONAME" + aptly_delete[repo_name])
            task_id = await aptly.repo_packages_delete(repo_name, aptly_delete[repo_name])
            await aptly.wait_task(task_id)

        for pv in projectversions:
            await aptly.republish(dist, projectversions[pv][0], projectversions[pv][1])

        def remove_buildout():
            for build_id in build_ids:
                buildout = "/var/lib/molior/buildout/%d" % build_id
                try:
                    rmtree(buildout)
                except Exception:
                    pass
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.threadexc, remove_buildout)

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

        logger.info("aptly worker: Debian packages for build %d deleted" % build_id)

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

            # a source package waiting for its publish is not published
            srcbuild = topbuild.children[0]
            if srcbuild.buildstate == "needs_publish":
                await srcbuild.set_publish_failed()

            for deb in srcbuild.children:
                # abort on build node
                if deb.buildstate in ["building", "scheduled"]:
                    await enqueue_backend({"abort": deb.id})

                if deb.buildstate in ["new", "needs_build", "scheduled"]:
                    await deb.set_failed()

                # a build waiting for its publish is not published
                if deb.buildstate == "needs_publish":
                    await deb.set_publish_failed()

                if deb.buildtask:
                    session.delete(deb.buildtask)

            await topbuild.set_failed()
            session.commit()

    async def _abort_projectversion(self, args):
        """Abort all unfinished builds of a projectversion (admin action)."""
        projectversion_id = args[0]
        logger.info("aptly worker: aborting all builds of projectversion %d", projectversion_id)

        with Session() as session:
            debs = session.query(Build).filter(
                Build.projectversion_id == projectversion_id,
                Build.buildtype == "deb",
                Build.buildstate.in_(["new", "needs_build", "scheduled", "building", "needs_publish", "publishing"]),
            ).all()
            for deb in debs:
                # FIXME: the kubernetes backend does not implement abort, running pods are left behind
                if deb.buildstate in ["building", "scheduled"]:
                    await enqueue_backend({"abort": deb.id})
                if deb.buildtask:
                    session.delete(deb.buildtask)
                topbuild = deb.parent.parent if deb.parent else None
                if topbuild:
                    await topbuild.log("E: aborting build on user request\n")
                if deb.buildstate == "needs_publish":
                    await deb.set_publish_failed()  # it is built, only the publish is aborted
                else:
                    await deb.set_failed()
                session.commit()

            # source builds only belonging to this projectversion
            # (a source build which is building runs inside molior and cannot be aborted)
            sources = session.query(Build).filter(
                Build.buildtype == "source",
                text("build.projectversions = ARRAY[%d]" % int(projectversion_id)),
                Build.buildstate.in_(["new", "needs_build", "needs_publish", "publishing"]),
            ).all()
            for source in sources:
                if source.parent:
                    await source.parent.log("E: aborting build on user request\n")
                if source.buildstate == "needs_publish":
                    await source.set_publish_failed()
                else:
                    await source.set_failed()
                session.commit()

            building = session.query(Build).filter(
                Build.buildtype == "source",
                text("build.projectversions = ARRAY[%d]" % int(projectversion_id)),
                Build.buildstate == "building",
            ).count()
            logger.info("aptly worker: aborted %d deb and %d source builds, %d source builds still building",
                        len(debs), len(sources), building)

    async def _remove_s3(self, args):
        projectversion_id = args[0]
        s3_endpoint = args[1]
        s3_path = args[2]

        with Session() as db:
            projectversion = get_projectversion_byid(projectversion_id, db)
            if not projectversion:
                logger.error("remove s3 projectversion: projectversion %d not found" % projectversion_id)
                return

        publish_s3 = f"{s3_endpoint}:{s3_path.replace('/', '_')}"  # on aptly, directory separatos is _ for publishing
        logger.info(f"aptly worker: Deleting S3 endpoint {publish_s3}")
        aptly = get_aptly_connection()
        try:
            task_id = await aptly.publish_drop(f"s3:{publish_s3}", "stable")
            if not await aptly.wait_task(task_id):
                logger.error(f"Error deleting S3 endpoint {publish_s3}")
        except Exception:
            logger.error(f"Error deleting S3 endpoint {publish_s3}")

    async def _publish_s3(self, args):
        projectversion_id = args[0]

        with Session() as db:
            projectversion = get_projectversion_byid(projectversion_id, db)
            if not projectversion:
                logger.error("remove s3 projectversion: projectversion %d not found" % projectversion_id)
                return
            s3_endpoint = projectversion.s3_endpoint
            s3_path = projectversion.s3_path
            publish_name = "{}_{}_repos_{}_{}".format(projectversion.basemirror.project.name,
                                                      projectversion.basemirror.name, projectversion.project.name,
                                                      projectversion.name)
            archs = db2array(projectversion.mirror_architectures)

        publish_s3 = f"{s3_endpoint}:{s3_path.replace('/', '_')}"  # on aptly, directory separatos is _ for publishing
        aptly = get_aptly_connection()
        snapshot_name = get_snapshot_name(publish_name, "stable", temporary=False)
        logger.info(f"Publishing to S3 endpoint {publish_s3} snapshot {snapshot_name} {archs}")
        task_id = await aptly.snapshot_publish(snapshot_name, "main", archs, "stable", f"s3:{publish_s3}")
        if not await aptly.wait_task(task_id):
            logger.error(f"Error publishing to S3 endpoint {publish_s3}")

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
                    args = task.get("delete_deb_build")
                    if args:
                        handled = True
                        await self._delete_deb_build(args)

                if not handled:
                    args = task.get("abort")
                    if args:
                        handled = True
                        await self._abort(args)

                if not handled:
                    args = task.get("abort_projectversion")
                    if args:
                        handled = True
                        await self._abort_projectversion(args)

                if not handled:
                    args = task.get("remove_s3")
                    if args:
                        handled = True
                        await self._remove_s3(args)

                if not handled:
                    args = task.get("publish_s3")
                    if args:
                        handled = True
                        await self._publish_s3(args)

                if not handled:
                    args = task.get("cleanup")
                    if args == []:
                        handled = True
                        await self._cleanup(args)

                if not handled:
                    logger.error("aptly worker got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("aptly task terminated")
