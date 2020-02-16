import asyncio
import operator

from launchy import Launchy
from sqlalchemy import or_

from molior.app import logger
from molior.model.database import Session
from molior.model.build import Build
from molior.model.buildvariant import BuildVariant
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion
from molior.model.architecture import Architecture
from molior.model.chroot import Chroot
from molior.molior.notifier import build_added
from molior.aptly.errors import AptlyError, NotFoundError
from molior.molior.utils import get_aptly_connection
from molior.molior.buildlogger import write_log, write_log_title
from molior.molior.debianrepository import DebianRepository
from ..ops import DebSrcPublish, DebPublish


async def startup_mirror(task_queue):
    """
    Starts a finalize_mirror task in the asyncio event loop
    for all mirrors which have the state 'updating'
    """
    loop = asyncio.get_event_loop()
    apt = get_aptly_connection()

    with Session() as session:
        # get mirrors in updating state
        query = session.query(ProjectVersion)  # pylint: disable=no-member
        query = query.join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(True))
        query = query.filter(or_(ProjectVersion.mirror_state == "updating", ProjectVersion.mirror_state == "publishing"))

        if not query.count():
            return

        mirrors = query.all()
        tasks = await apt.get_tasks()

        for mirror in mirrors:
            # FIXME: only one buildvariant supported
            base_mirror = ""
            base_mirror_version = ""
            taskname = "Update mirror"
            buildstate = "building"
            if mirror.mirror_state == "publishing":
                taskname = "Publish snapshot:"
                buildstate = "publishing"
            if not mirror.project.is_basemirror:
                base_mirror = mirror.buildvariants[0].base_mirror.project.name
                base_mirror_version = mirror.buildvariants[0].base_mirror.name
                task_name = "{} {}-{}-{}-{}".format(taskname, base_mirror, base_mirror_version, mirror.project.name, mirror.name)
            else:
                task_name = "{} {}-{}".format(taskname, mirror.project.name, mirror.name)

            m_tasks = None
            if tasks:
                m_tasks = [task for task in tasks if task["Name"] == task_name]
            if not m_tasks:
                # No task on aptly found
                mirror.mirror_state = "error"
                session.commit()  # pylint: disable=no-member
                continue

            m_task = max(m_tasks, key=operator.itemgetter("ID"))

            build = (
                session.query(Build)
                .filter(
                    Build.buildtype == "mirror",
                    Build.buildstate == buildstate,
                    Build.projectversion_id == mirror.id,
                )
                .first()
            )
            if not build:
                # No task on aptly found
                mirror.mirror_state = "error"
                session.commit()  # pylint: disable=no-member
                continue

            # FIXME: do not allow db cleanup while mirroring

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
                    m_task.get("ID"),
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

    apt = get_aptly_connection()
    # FIXME: do not allow db cleanup while mirroring
    task_id = await apt.mirror_update(base_mirror, base_mirror_version, mirror, version)

    logger.info("start update progress: aptly task %s", task_id)
    loop = asyncio.get_event_loop()
    loop.create_task(finalize_mirror(task_queue, build_id, base_mirror, base_mirror_version,
                                     mirror, version, components, task_id))


async def finalize_mirror(task_queue, build_id, base_mirror, base_mirror_version, mirror, version, components, task_id):
    """
    """
    try:
        mirrorname = "{}-{}".format(mirror, version)
        logger.info("finalizing mirror %s task %d, build_%d", mirrorname, task_id, build_id)

        with Session() as session:

            # FIXME: get entry from build.projectversion_id
            query = session.query(ProjectVersion)  # pylint: disable=no-member
            query = query.join(Project, Project.id == ProjectVersion.project_id)
            query = query.filter(Project.is_mirror.is_(True))
            query = query.filter(ProjectVersion.name == version)
            entry = query.filter(Project.name == mirror).first()

            if not entry:
                logger.error("finalize mirror: mirror '%s' not found", mirrorname)
                return

            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("aptly worker: mirror build with id %d not found", build_id)
                return

            apt = get_aptly_connection()

            if entry.mirror_state == "updating":
                while True:
                    try:
                        upd_progress = await apt.mirror_get_progress(task_id)
                    except Exception as exc:
                        logger.error("update mirror %s get progress exception: %s", mirrorname, exc)
                        entry.mirror_state = "error"
                        await build.set_failed()
                        session.commit()  # pylint: disable=no-member
                        return

                    # 0: init, 1: running, 2: success, 3: failed
                    if upd_progress["State"] == 2:
                        break

                    if upd_progress["State"] == 3:
                        logger.error("update mirror %s progress error", mirrorname)
                        entry.mirror_state = "error"
                        await build.set_failed()
                        session.commit()  # pylint: disable=no-member
                        return

                    logger.info("mirrored %d/%d files (%.02f%%), %.02f/%.02fGB (%.02f%%)",
                                upd_progress["TotalNumberOfPackages"] - upd_progress["RemainingNumberOfPackages"],
                                upd_progress["TotalNumberOfPackages"], upd_progress["PercentPackages"],
                                (upd_progress["TotalDownloadSize"] - upd_progress["RemainingDownloadSize"])
                                / 1024.0 / 1024.0 / 1024.0,
                                upd_progress["TotalDownloadSize"] / 1024.0 / 1024.0 / 1024.0,
                                upd_progress["PercentSize"],
                                )

                    await asyncio.sleep(2)

                await apt.delete_task(task_id)

                write_log(build.id, "I: creating snapshot\n")

                await build.set_publishing()
                session.commit()

                # snapshot after initial download
                logger.info("creating snapshot for: %s", mirrorname)
                try:
                    task_id = await apt.mirror_snapshot(base_mirror, base_mirror_version, mirror, version)
                except AptlyError as exc:
                    logger.error("error creating mirror %s snapshot: %s", mirrorname, exc)
                    entry.mirror_state = "error"
                    await build.set_publish_failed()
                    session.commit()  # pylint: disable=no-member
                    return

                while True:
                    try:
                        task_state = await apt.get_task_state(task_id)
                    except Exception:
                        logger.exception("error getting mirror %s state", mirrorname)
                        entry.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()  # pylint: disable=no-member
                        return
                    # States:
                    # 0: init, 1: running, 2: success, 3: failed
                    if task_state["State"] == 2:
                        break
                    if task_state["State"] == 3:
                        logger.error("creating mirror %s snapshot failed", mirrorname)
                        entry.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()  # pylint: disable=no-member
                        return

                    # FIMXE: why sleep ?
                    await asyncio.sleep(2)

                await apt.delete_task(task_id)

                entry.mirror_state = "publishing"
                session.commit()  # pylint: disable=no-member

                # publish new snapshot
                write_log(build.id, "I: publishing mirror\n")
                logger.info("publishing snapshot: %s", mirrorname)
                try:
                    task_id = await apt.mirror_publish(base_mirror, base_mirror_version, mirror, version,
                                                       entry.mirror_distribution, components)
                except Exception as exc:
                    logger.error("error publishing mirror %s snapshot: %s", mirrorname, str(exc))
                    entry.mirror_state = "error"
                    await build.set_publish_failed()
                    session.commit()  # pylint: disable=no-member
                    await apt.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror, version)
                    return

            if entry.mirror_state == "publishing":
                while True:
                    try:
                        upd_progress = await apt.mirror_get_progress(task_id)
                    except Exception as exc:
                        logger.error("error publishing mirror %s: %s", mirrorname, str(exc))

                        entry.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()  # pylint: disable=no-member

                        await apt.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror, version)
                        return

                    # States:
                    # 0: init, 1: running, 2: success, 3: failed
                    if upd_progress["State"] == 2:
                        break
                    if upd_progress["State"] == 3:
                        logger.error("error publishing mirror %s snapshot", mirrorname)
                        entry.mirror_state = "error"
                        await build.set_publish_failed()
                        session.commit()  # pylint: disable=no-member
                        await apt.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror, version)
                        return

                    logger.info(
                        "published %d/%d packages (%.02f%%)",
                        upd_progress["TotalNumberOfPackages"]
                        - upd_progress["RemainingNumberOfPackages"],
                        upd_progress["TotalNumberOfPackages"],
                        upd_progress["PercentPackages"],
                    )

                    await asyncio.sleep(2)

            if entry.project.is_basemirror:
                for arch_name in entry.mirror_architectures[1:-1].split(","):
                    arch = (
                        session.query(Architecture)
                        .filter(Architecture.name == arch_name)
                        .first()
                    )  # pylint: disable=no-member
                    if not arch:
                        await build.set_publish_failed()
                        logger.error("finalize mirror: architecture '%s' not found", arch_name)
                        return

                    buildvariant = BuildVariant(base_mirror=entry, architecture=arch)
                    session.add(buildvariant)  # pylint: disable=no-member

                    write_log(build.id, "I: starting chroot environments build\n")

                    chroot_build = Build(
                        version=version,
                        git_ref=None,
                        ci_branch=None,
                        is_ci=None,
                        versiontimestamp=None,
                        sourcename=mirror,
                        buildstate="new",
                        buildtype="chroot",
                        projectversion_id=build.projectversion_id,
                        buildconfiguration=None,
                        parent_id=build.id,
                        sourcerepository=None,
                        maintainer=None,
                    )

                    session.add(chroot_build)
                    session.commit()
                    chroot_build.log_state("created")
                    await build_added(chroot_build)

                    await chroot_build.set_needs_build()
                    session.commit()

                    await chroot_build.set_scheduled()
                    session.commit()

                    chroot = Chroot(buildvariant=buildvariant, ready=False)
                    session.add(chroot)
                    session.commit()

                    loop = asyncio.get_event_loop()
                    loop.create_task(
                        create_schroot(
                            task_queue,
                            chroot.id,
                            chroot_build.id,
                            buildvariant.base_mirror.mirror_distribution,
                            buildvariant.base_mirror.project.name,
                            buildvariant.base_mirror.name,
                            buildvariant.architecture.name,
                        )
                    )

            entry.is_locked = True
            entry.mirror_state = "ready"
            session.commit()  # pylint: disable=no-member

            await build.set_successful()
            session.commit()

            logger.info("mirror %s succesfully created", mirrorname)
            write_log_title(build.id, "Done")

    except Exception as exc:
        logger.exception(exc)


async def create_schroot(task_queue, chroot_id, build_id, dist, name, version, arch):
    """
    Creates a sbuild chroot and other build environments.

    Args:
        dist (str): The distrelease
        version (str): The version
        arch (str): The architecture

    Returns:
        bool: True on success
    """

    with Session() as session:
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("aptly worker: mirror build with id %d not found", build_id)
            return False

        write_log_title(build_id, "Chroot Environment")

        await build.set_building()
        session.commit()

        logger.info("creating build environments for %s-%s-%s", dist, version, arch)
        write_log(build_id, "Creating build environments for %s-%s-%s\n\n" % (dist, version, arch))

        async def outh(line):
            write_log(build_id, "%s\n" % line)

        process = Launchy(["sudo", "run-parts", "-a", "build", "-a", dist, "-a", name, "-a", version, "-a", arch,
                          "/etc/molior/mirror-hooks.d"], outh, outh)
        await process.launch()
        ret = await process.wait()

        if not ret == 0:
            logger.error("error creating build env")
            write_log(build_id, "Error creating build environment\n")
            write_log_title(build_id, "Done", no_footer_newline=True)
            await build.set_failed()
            session.commit()
            return False

        await build.set_needs_publish()
        session.commit()

        await build.set_publishing()
        session.commit()

        process = Launchy(["sudo", "run-parts", "-a", "publish", "-a", dist, "-a", name, "-a", version, "-a", arch,
                           "/etc/molior/mirror-hooks.d"], outh, outh)
        await process.launch()
        ret = await process.wait()

        if not ret == 0:
            logger.error("error publishing build env")
            write_log(build_id, "Error publishing build environment\n")
            write_log_title(build_id, "Done", no_footer_newline=True)
            await build.set_publish_failed()
            session.commit()
            return False

        write_log(build_id, "\n")
        write_log_title(build_id, "Done", no_footer_newline=True)
        await build.set_successful()
        session.commit()

        chroot = session.query(Chroot).filter(Chroot.id == chroot_id).first()
        chroot.ready = True
        session.commit()

        # Schedule builds
        args = {"schedule": []}
        await task_queue.put(args)

        return True


class AptlyWorker:
    """
    Source Packaging worker thread

    """

    def __init__(self, aptly_queue, task_queue):
        self.aptly_queue = aptly_queue
        self.task_queue = task_queue

    async def _create_mirror(self, args, session):
        (
            mirror,
            url,
            mirror_distribution,
            components,
            keys,
            keyserver,
            is_basemirror,
            architectures,
            version,
            key_url,
            basemirror_id,
            download_sources,
            download_installer,
        ) = args

        build = Build(
            version=version,
            git_ref=None,
            ci_branch=None,
            is_ci=False,
            versiontimestamp=None,
            sourcename=mirror,
            buildstate="new",
            buildtype="mirror",
            buildconfiguration=None,
            sourcerepository=None,
            maintainer=None,
        )

        build.log_state("created")
        session.add(build)
        await build_added(build)
        session.commit()

        write_log_title(build.id, "Create Mirror")

        mirror_project = (
            session.query(Project)  # pylint: disable=no-member
            .filter(Project.name == mirror, Project.is_mirror.is_(True))
            .first()
        )
        if not mirror_project:
            mirror_project = Project(
                name=mirror, is_mirror=True, is_basemirror=is_basemirror
            )
            session.add(mirror_project)  # pylint: disable=no-member

        project_version = (
            session.query(ProjectVersion)
            .join(Project)
            .filter(  # pylint: disable=no-member
                Project.name == mirror, Project.is_mirror.is_(True)
            )
            .filter(ProjectVersion.name == version)
            .first()
        )

        if project_version:
            write_log(build.id, "W: mirror with name '%s' and version '%s' already exists\n" % (mirror, version))
            logger.error("mirror with name '%s' and version '%s' already exists", mirror, version)
            await build.set_successful()
            session.commit()
            return True

        base_mirror = None
        base_mirror_version = None
        db_buildvariant = None
        if not is_basemirror:
            db_basemirror = (
                session.query(ProjectVersion)  # pylint: disable=no-member
                .filter(ProjectVersion.id == basemirror_id)
                .first()
            )
            if not db_basemirror:
                write_log(build.id, "E: could not find a basemirror with id '%d'\n" % basemirror_id)
                logger.error("could not find a basemirror with id '%d'", basemirror_id)
                await build.set_failed()
                session.commit()
                return False

            base_mirror = db_basemirror.project.name
            base_mirror_version = db_basemirror.name
            db_buildvariant = (
                session.query(BuildVariant)  # pylint: disable=no-member
                .filter(BuildVariant.base_mirror_id == basemirror_id)
                .first()
            )

            if not db_buildvariant:
                write_log(build.id, "E: could not find a buildvariant for basemirror with id '%d'\n" % db_basemirror.id)
                logger.error("could not find a buildvariant for basemirror with id '%d'", db_basemirror.id)
                await build.set_failed()
                session.commit()
                return False

        mirror_project_version = ProjectVersion(
            name=version,
            project=mirror_project,
            mirror_url=url,
            mirror_distribution=mirror_distribution,
            mirror_components=",".join(components),
            mirror_architectures="{" + ",".join(architectures) + "}",
            mirror_with_sources=download_sources,
            mirror_with_installer=download_installer,
        )

        if db_buildvariant:
            mirror_project_version.buildvariants.append(db_buildvariant)

        session.add(mirror_project_version)
        session.commit()

        build.projectversion_id = mirror_project_version.id
        session.commit()

        write_log(build.id, "I: adding GPG keys\n")

        apt = get_aptly_connection()
        if key_url:
            try:
                await apt.gpg_add_key(key_url=key_url)
            except AptlyError as exc:
                write_log(build.id, "E: Error adding keys from '%s'\n" % key_url)
                logger.error("key error: %s", exc)
                await build.set_failed()
                return False
        elif keyserver and keys:
            try:
                await apt.gpg_add_key(key_server=keyserver, keys=keys)
            except AptlyError as exc:
                write_log(build.id, "E: Error adding keys %s\n" % str(keys))
                logger.error("key error: %s", exc)
                await build.set_failed()
                return False

        write_log(build.id, "I: creating mirror\n")
        try:
            await apt.mirror_create(
                mirror,
                version,
                base_mirror,
                base_mirror_version,
                url,
                mirror_distribution,
                components,
                architectures,
                download_sources=download_sources,
                download_udebs=download_installer,
                download_installer=download_installer,
            )

        except NotFoundError as exc:
            write_log(build.id, "E: aptly seems to be not available: %s\n" % str(exc))
            logger.error("aptly seems to be not available: %s", str(exc))
            await build.set_failed()
            return False

        except AptlyError as exc:
            write_log(build.id, "E: failed to create mirror %s on aptly: %s\n" % (mirror, str(exc)))
            logger.error("failed to create mirror %s on aptly: %s", mirror, str(exc))
            await build.set_failed()
            return False

        args = {"update_mirror": [
                build.id,
                mirror_project_version.id,
                base_mirror,
                base_mirror_version,
                mirror,
                version,
                components]}
        await self.aptly_queue.put(args)

    async def _update_mirror(self, args, session):
        build_id = args[0]
        mirror_id = args[1]
        base_mirror = args[2]
        base_mirror_version = args[3]
        mirror_name = args[4]
        mirror_version = args[5]
        components = args[6]

        write_log(build_id, "I: updating mirror\n")

        mirror = session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()
        if not mirror:
            write_log(build_id, "E: aptly worker: mirror with id %d not found\n" % mirror_id)
            logger.error("aptly worker: mirror with id %d not found", mirror_id)
            return

        build = session.query(Build).filter(Build.projectversion_id == mirror_id and Build.buildtype == "mirror").first()
        if not build:
            write_log(build_id, "E: aptly worker: no build found for mirror with id %d\n" % str(mirror_id))
            logger.error("aptly worker: no build found for mirror with id %d", str(mirror_id))
            return

        await build.set_building()
        session.commit()

        try:
            await update_mirror(
                self.task_queue,
                build_id,
                base_mirror,
                base_mirror_version,
                mirror_name,
                mirror_version,
                components,
            )
        except NotFoundError as exc:
            write_log(build_id, "E: aptly seems to be not available: %s\n" % str(exc))
            logger.error("aptly seems to be not available: %s", str(exc))
            # FIXME: remove from db
            await build.set_failed()
            session.commit()
            return
        except AptlyError as exc:
            write_log(build_id, "E: failed to update mirror %s on aptly: %s\n" % (mirror_name, str(exc)))
            logger.error("failed to update mirror %s on aptly: %s", mirror_name, str(exc))
            # FIXME: remove from db
            await build.set_failed()
            session.commit()
            return

        mirror.mirror_state = "updating"
        session.commit()  # pylint: disable=no-member

    async def _src_publish(self, args, session):
        build_id = args[0]
        projectversion_ids = args[1]

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("aptly worker: build with id %d not found", build_id)
            return

        await build.set_publishing()
        session.commit()

        ret = False
        try:
            ret = await DebSrcPublish(build.id, build.sourcename, build.version, projectversion_ids, build.is_ci)
        except Exception as exc:
            logger.exception(exc)

        if not ret:
            write_log(build.parent.id, "E: publishing source package failed\n")
            write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)
            await build.set_publish_failed()
            session.commit()
            return

        await build.set_successful()
        session.commit()

        write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)

        write_log(build.parent.id, "I: scheduling deb package builds\n")
        # schedule child builds
        childs = session.query(Build).filter(Build.parent_id == build.id).all()
        if not childs:
            logger.error("publishsrc_succeeded no build childs found for %d", build_id)
            write_log(build.parent.id, "E: no deb builds found\n")
            write_log_title(build.parent.id, "Done", no_footer_newline=True, no_header_newline=True)
            await build.parent.set_failed()
            session.commit()
            return False

        for child in childs:
            await child.set_needs_build()
            session.commit()

        # Schedule builds
        args = {"schedule": []}
        await self.task_queue.put(args)

    async def _publish(self, args, session):
        build_id = args[0]
        await asyncio.ensure_future(DebPublish(self.task_queue, build_id))
        # FIXME Error handling

    async def _drop_publish(self, args, _):
        base_mirror_name = args[0]
        base_mirror_version = args[1]
        projectname = args[2]
        projectversion = args[3]
        dist = args[4]
        logger.info("aptly worker: got drop publish task: %s/%s %s %s %s",
                    base_mirror_name, base_mirror_version, projectname, projectversion, dist)

        apt = get_aptly_connection()
        await apt.publish_drop(base_mirror_name, base_mirror_version, projectname, projectversion, dist)

    async def _init_repository(self, args, session):
        basemirror_name = args[1]
        basemirror_version = args[2]
        project_name = args[3]
        project_version = args[4]
        architectures = args[5]
        logger.info("aptly worker: init debian repository: 'basemirror %s-%s, projectversion: %s/%s, archs: [%s]",
                    basemirror_name,
                    basemirror_version,
                    project_name,
                    project_version,
                    ", ".join(architectures))

        await DebianRepository(basemirror_name, basemirror_version, project_name, project_version, architectures).init()

    async def _cleanup(self, args, session):
        logger.info("aptly worker: running cleanup")
        apt = get_aptly_connection()
        await apt.cleanup()

    async def run(self):
        """
        Run the worker task.
        """

        await startup_mirror(self.task_queue)

        while True:
            try:
                task = await self.aptly_queue.get()
                if task is None:
                    logger.info("aptly worker: got emtpy task, aborting...")
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
