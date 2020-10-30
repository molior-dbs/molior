import os
import shlex

from launchy import Launchy
from pathlib import Path
from aiofile import AIOFile

from ..app import logger
from ..tools import strip_epoch_version, db2array
from ..molior.debianrepository import DebianRepository
from ..molior.configuration import Configuration

from ..model.database import Session
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


async def DebSrcPublish(session, build):
    """
    Publishes given src_files/src package to given
    projectversion debian repo.

    Args:
        build: source package build

    Returns:
        bool: True if successful, otherwise False.
    """

    build.log("\n")
    build.logtitle("Publishing")
    sourcepath = Path(Configuration().working_dir) / "repositories" / str(build.sourcerepository.id)
    srcfiles = await debchanges_get_files(sourcepath, build.sourcename, build.version)
    if not srcfiles:
        logger.error("no source files found")
        return False

    build.add_files(session, srcfiles)

    publish_files = []
    for f in srcfiles:
        logger.debug("publisher: adding %s", f)
        publish_files.append("{}/{}".format(sourcepath, f))

    build.log_state("publishing {} for projectversion ids {}".format(build.sourcename, str(build.projectversions)))

    ret = False
    for projectversion_id in build.projectversions:
        with Session() as session:
            projectversion = session.query(ProjectVersion) .filter(ProjectVersion.id == projectversion_id) .first()
            if not projectversion:
                logger.error("publisher: error finding projectversion {}".format(projectversion_id))
                build.log("E: error finding projectversion {}\n".format(projectversion_id))
                continue

            build.log("I: publishing for %s\n" % projectversion.fullname)
            basemirror_name = projectversion.basemirror.project.name
            basemirror_version = projectversion.basemirror.name
            project_name = projectversion.project.name
            project_version = projectversion.name
            archs = db2array(projectversion.mirror_architectures)

        debian_repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
        try:
            await debian_repo.add_packages(publish_files, ci_build=build.is_ci)
            ret = True
        except Exception as exc:
            build.log("E: error adding files to projectversion {}\n".format(projectversion.fullname))
            logger.exception(exc)

    build.log("\n")

    if ret:  # only delete if published, allow republish
        files2delete = publish_files
        v = strip_epoch_version(build.version)
        changes_file = "{}_{}_{}.changes".format(build.sourcename, v, "source")
        files2delete.append("{}/{}".format(sourcepath, changes_file))
        for f in files2delete:
            logger.debug("publisher: removing %s", f)
            try:
                os.remove(f)
            except Exception as exc:
                logger.exception(exc)

    return ret


async def publish_packages(session, build, out_path):
    """
    Publishes given packages to given
    publish point.

    Args:
        build (Build): The build model.
        out_path (Path): The build output path.

    Returns:
        bool: True if successful, otherwise False.
    """

    outfiles = await debchanges_get_files(out_path, build.sourcename, build.version, build.architecture)
    build.add_files(session, outfiles)
    # FIXME: commit

    files2upload = []
    for f in outfiles:
        logger.debug("publisher: adding %s", f)
        files2upload.append("{}/{}".format(out_path, f))

    count_files = len(files2upload)
    if count_files == 0:
        logger.error("publisher: build %d: no files to upload", build.id)
        build.log("E: no debian packages found to upload\n")
        build.parent.parent.log("E: build %d failed\n" % build.id)
        return False

    # FIXME: check on startup
    key = Configuration().debsign_gpg_email
    if not key:
        logger.error("Signing key not defined in configuration")
        build.log("E: no signinig key defined in configuration\n")
        build.parent.parent.log("E: build %d failed\n" % build.id)
        return False

    build.log("Signing packages:\n")

    async def outh(line):
        build.log("%s\n" % line)

    v = strip_epoch_version(build.version)
    changes_file = "{}_{}_{}.changes".format(build.sourcename, v, build.architecture)

    cmd = "debsign -pgpg1 -k{} {}".format(key, changes_file)
    process = Launchy(shlex.split(cmd), outh, outh, cwd=str(out_path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        logger.error("debsign failed")
        return False

    logger.debug("publisher: uploading %d file%s", count_files, "" if count_files == 1 else "s")

    basemirror_name = build.projectversion.basemirror.project.name
    basemirror_version = build.projectversion.basemirror.name
    project_name = build.projectversion.project.name
    project_version = build.projectversion.name
    archs = db2array(build.projectversion.mirror_architectures)

    debian_repo = DebianRepository(basemirror_name, basemirror_version, project_name, project_version, archs)
    ret = False
    try:
        await debian_repo.add_packages(files2upload, ci_build=build.is_ci)
        ret = True
    except Exception as exc:
        build.log("E: error uploading files to repository\n")
        logger.exception(exc)

    files2delete = files2upload
    files2delete.append("{}/{}".format(out_path, changes_file))
    for f in files2delete:
        logger.debug("publisher: removing %s", f)
        os.remove(f)

    return ret


async def DebPublish(session, build):
    """
    Publishes given src_files/src package to given
    projectversion debian repo.

    Args:
        projectversion_id (int): The projectversion's id.
        src_files (list): List of file paths to the src files.

    Returns:
        bool: True if successful, otherwise False.
    """

    try:
        out_path = Path(Configuration().working_dir) / "buildout" / str(build.id)
        build.parent.parent.log("I: publishing build %d\n" % build.id)
        build.logtitle("Publishing", no_header_newline=False)
        if not await publish_packages(session, build, out_path):
            logger.error("publisher: error publishing build %d" % build.id)
            return False
    except Exception as exc:
        logger.error("publisher: error publishing build %d" % build.id)
        logger.exception(exc)
        return False
    finally:
        buildtask = session.query(BuildTask).filter(BuildTask.build == build).first()
        if buildtask:
            session.delete(buildtask)
    return True
