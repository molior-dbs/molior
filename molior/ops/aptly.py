import os
import shlex

from launchy import Launchy
from pathlib import Path
from aiofile import AIOFile

from ..app import logger
from ..tools import strip_epoch_version, write_log, write_log_title
from ..molior.debianrepository import DebianRepository
from ..molior.configuration import Configuration
from ..molior.notifier import send_mail_notification

from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.projectversion import ProjectVersion


async def debchanges_get_files(sourcepath, sourcename, version, arch="source"):
    v = strip_epoch_version(version)
    changes_file = "{}/{}_{}_{}.changes".format(sourcepath, sourcename, v, arch)
    files = []
    try:
        async with AIOFile(changes_file, "rb") as f:
            data = await f.read()
            file_tag = False
            for line in str(data, 'utf-8').split('\n'):
                line = line.rstrip()
                if not file_tag:
                    if line == "Files:":
                        file_tag = True
                else:
                    if not line.startswith(" "):
                        break
                    line = line.lstrip()
                    parts = line.split(" ")
                    files.append(parts[4])
    except Exception as exc:
        logger.exception(exc)
    return files


async def DebSrcPublish(build):
    """
    Publishes given src_files/src package to given
    projectversion debian repo.

    Args:
        build: source package build

    Returns:
        bool: True if successful, otherwise False.
    """

    await write_log(build.id, "\n")
    await write_log_title(build.id, "Publishing")
    sourcepath = Path(Configuration().working_dir) / "repositories" / str(build.sourcerepository.id)
    srcfiles = await debchanges_get_files(sourcepath, build.sourcename, build.version)
    if not srcfiles:
        logger.error("no source files found")
        return False

    publish_files = []
    for f in srcfiles:
        logger.debug("publisher: adding %s", f)
        publish_files.append("{}/{}".format(sourcepath, f))

    logger.info("publisher: publishing %s for projectversion ids %s", build.sourcename, str(build.projectversions))

    ret = False
    for projectversion_id in build.projectversions:
        with Session() as session:
            projectversion = session.query(ProjectVersion) .filter(ProjectVersion.id == projectversion_id) .first()
            if not projectversion:
                logger.error("publisher: error finding projectversion {}".format(projectversion_id))
                await write_log(build.id, "E: error finding projectversion {}\n".format(projectversion_id))
                continue

            await write_log(build.id, "I: publishing for %s\n" % projectversion.fullname)
            basemirror_name = projectversion.buildvariants[0].base_mirror.project.name
            basemirror_version = projectversion.buildvariants[0].base_mirror.name
            project_name = projectversion.project.name
            project_version = projectversion.name
            archs = [bdv.architecture.name for bdv in projectversion.buildvariants]

        debian_repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
        try:
            await debian_repo.add_packages(publish_files, ci_build=build.is_ci)
            ret = True
        except Exception as exc:
            await write_log(build.id, "E: error adding files to projectversion {}\n".format(projectversion.fullname))
            logger.exception(exc)

    await write_log(build.id, "\n")

    if ret:
        files2delete = publish_files
        v = strip_epoch_version(build.version)
        changes_file = "{}_{}_{}.changes".format(build.sourcename, v, "source")
        files2delete.append("{}/{}".format(sourcepath, changes_file))
        for f in files2delete:
            logger.info("publisher: removing %s", f)
            try:
                os.remove(f)
            except Exception as exc:
                logger.exception(exc)

    return ret


async def publish_packages(build, out_path):
    """
    Publishes given packages to given
    publish point.

    Args:
        build (Build): The build model.
        out_path (Path): The build output path.

    Returns:
        bool: True if successful, otherwise False.
    """

    arch = build.buildconfiguration.buildvariant.architecture.name
    outfiles = await debchanges_get_files(out_path, build.sourcename, build.version, arch)

    files2upload = []
    for f in outfiles:
        logger.info("publisher: adding %s", f)
        files2upload.append("{}/{}".format(out_path, f))

    count_files = len(files2upload)
    if count_files == 0:
        logger.error("publisher: build %d: no files to upload", build.id)
        await write_log(build.id, "E: no debian packages found to upload\n")
        await write_log(build.parent.parent.id, "E: build %d failed\n" % build.id)
        return False

    # FIXME: check on startup
    key = Configuration().debsign_gpg_email
    if not key:
        logger.error("Signing key not defined in configuration")
        await write_log(build.id, "E: no signinig key defined in configuration\n")
        await write_log(build.parent.parent.id, "E: build %d failed\n" % build.id)
        return False

    await write_log(build.id, "I: Signing packages\n")

    async def outh(line):
        await write_log(build.id, "%s\n" % line)

    v = strip_epoch_version(build.version)
    changes_file = "{}_{}_{}.changes".format(build.sourcename, v, arch)

    cmd = "debsign -pgpg1 -k{} {}".format(key, changes_file)
    process = Launchy(shlex.split(cmd), outh, outh, cwd=str(out_path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        logger.error("debsign failed")
        return False

    logger.info("publisher: uploading %d file%s", count_files, "" if count_files == 1 else "s")
    projectversion = build.buildconfiguration.projectversions[0]

    basemirror_name = projectversion.buildvariants[0].base_mirror.project.name
    basemirror_version = projectversion.buildvariants[0].base_mirror.name
    project_name = projectversion.project.name
    project_version = projectversion.name
    archs = [bdv.architecture.name for bdv in projectversion.buildvariants]

    debian_repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
    await debian_repo.add_packages(files2upload, ci_build=build.is_ci)

    files2delete = files2upload
    files2delete.append("{}/{}".format(out_path, changes_file))
    for f in files2delete:
        logger.debug("publisher: removing %s", f)
        os.remove(f)

    return True


async def DebPublish(task_queue, build_id):
    """
    Publishes given src_files/src package to given
    projectversion debian repo.

    Args:
        projectversion_id (int): The projectversion's id.
        src_files (list): List of file paths to the src files.

    Returns:
        bool: True if successful, otherwise False.
    """

    with Session() as session:

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("build_succeeded: no build found for %d", build_id)
            return
        await build.set_needs_publish()
        session.commit()

        logger.info("publisher: publishing build %d", build_id)
        await build.set_publishing()
        session.commit()
        try:
            out_path = Path(Configuration().working_dir) / "buildout" / str(build_id)
            await write_log(build.parent.parent.id, "I: publishing build %d\n" % build.id)
            await write_log_title(build_id, "Publishing", no_header_newline=False)
            if not await publish_packages(build, out_path):
                logger.error("publisher: error publishing build %d" % build_id)
                await write_log(build.parent.parent.id, "E: publishing build %d failed\n" % build.id)
                await write_log_title(build_id, "Done", no_footer_newline=True, no_header_newline=False)
                await build.set_publish_failed()
                session.commit()
                return
        except Exception as exc:
            logger.error("publisher: error publishing build %d" % build_id)
            await write_log(build.parent.parent.id, "E: publishing build %d failed\n" % build.id)
            await write_log_title(build_id, "Done", no_footer_newline=True, no_header_newline=False)
            logger.exception(exc)
            await build.set_publish_failed()
            session.commit()
            return
        finally:
            buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
            session.delete(buildtask)
            session.commit()

        await write_log_title(build_id, "Done", no_footer_newline=True, no_header_newline=False)
        await build.set_successful()
        session.commit()

        if not build.is_ci:
            send_mail_notification(build)

        # Schedule builds
        args = {"schedule": []}
        await task_queue.put(args)
