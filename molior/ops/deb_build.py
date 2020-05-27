import asyncio
import shlex
import uuid
import os
import re

from launchy import Launchy
from sqlalchemy import or_
from pathlib import Path

from molior.app import logger
from molior.tools import get_changelog_attr, strip_epoch_version

from molior.model.database import Session
from molior.model.sourcerepository import SourceRepository
from molior.model.build import Build
from molior.model.buildtask import BuildTask
from molior.model.maintainer import Maintainer
from molior.model.chroot import Chroot
from molior.model.buildvariant import BuildVariant
from molior.model.architecture import Architecture
from molior.model.projectversion import ProjectVersion, get_projectversion_deps

from molior.molior.core import (
    get_target_arch,
    get_targets,
    get_buildconfigs,
    get_buildorder,
)

from molior.molior.buildlogger import write_log, write_log_title
from molior.molior.configuration import Configuration
from molior.molior.worker_backend import backend_queue

from .git import GitCheckout, GetBuildInfo


async def BuildDebSrc(repo_id, repo_path, build_id, ci_version, is_ci, author, email):
    write_log(build_id, "I: getting debian build information\n")
    src_package_name = await get_changelog_attr("Source", repo_path)
    version = await get_changelog_attr("Version", repo_path)
    repo_path = Path(repo_path)

    key = Configuration().debsign_gpg_email
    if not key:
        write_log(build_id, "E: Signing key not defined in configuration\n")
        logger.error("Signing key not defined in configuration")
        return False

    logger.info("%s: creating source package", src_package_name)
    write_log(build_id, "I: creating source package: %s (%s)\n" % (src_package_name, version))

    async def outh(line):
        line = line.strip()
        if line:
            write_log(build_id, "%s\n" % line)

    if is_ci:
        # in order to publish a sourcepackage for a ci build we need
        # to create a ci changelog with the correct version

        distribution = await get_changelog_attr("Distribution", repo_path)

        env = os.environ.copy()
        env["DEBFULLNAME"] = author
        env["DEBEMAIL"] = email
        dchcmd = "dch -v %s --distribution %s --force-distribution 'CI Build'" % (ci_version, distribution)
        version = ci_version

        process = Launchy(shlex.split(dchcmd), outh, outh, cwd=str(repo_path), env=env)
        await process.launch()
        ret = await process.wait()
        if ret != 0:
            logger.error("Error running dch for CI build")
            return False

    cmd = "dpkg-buildpackage -S -d -nc -I.git -pgpg1 -k{}".format(key)
    process = Launchy(shlex.split(cmd), outh, outh, cwd=str(repo_path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        write_log(build_id, "E: Error building source package\n")
        logger.error("source packaging failed, dpkg-builpackage returned %d", ret)
        return False

    logger.info("%s (%d): source package v%s created", src_package_name, repo_id, version)
    return True


async def BuildProcess(task_queue, aptly_queue, parent_build_id, repo_id, git_ref, ci_branch):
    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return

        write_log_title(parent_build_id, "Molior Build")

        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            write_log(parent_build_id, "E: source repository {} not found\n".format(repo_id))
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            session.commit()
            return

        write_log(parent_build_id, "I: git checkout {}\n".format(git_ref))

        # Checkout
        ret = await asyncio.ensure_future(GitCheckout(repo.src_path, git_ref, parent_build_id))
        if not ret:
            write_log(parent_build_id, "E: git checkout failed\n")
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

        write_log(parent_build_id, "\nI: get build information\n")
        info = None
        try:
            info = await GetBuildInfo(repo.src_path, git_ref)
        except Exception as exc:
            logger.exception(exc)

        if not info:
            write_log(parent_build_id, "E: Error getting build information\n")
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

        targets = get_targets(info.plain_targets, repo, session)
        if not targets:
            repo.log_state("unknown target projectversions in debian/molior.yml")
            write_log(parent_build_id, "E: the repository is not added to any projectversions referenced in debian/molior.yml\n")
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            repo.set_ready()
            await parent.set_failed()
            session.commit()
            return

        # check if it is a CI build
        # i.e. if gittag does not match version in debian/changelog
        is_ci = False
        gittag = ""

        async def outh(line):
            nonlocal gittag
            gittag += line

        process = Launchy(shlex.split("git describe --tags --abbrev=40"), outh, outh, cwd=str(repo.src_path))
        await process.launch()
        ret = await process.wait()
        if ret != 0:
            logger.error("error running git describe")
        else:
            v = strip_epoch_version(info.version)
            if not re.match("^v?{}$".format(v.replace("~", "-")), gittag):
                is_ci = True

        ci_cfg = Configuration().ci_builds
        ci_enabled = ci_cfg.get("enabled") if ci_cfg else False

        if is_ci and not ci_enabled:
            repo.log_state("CI builds are not enabled in configuration")
            write_log(parent_build_id, "E: CI builds are not enabled in configuration\n")
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_successful()
            repo.set_ready()
            session.commit()
            return

        parent.is_ci = is_ci
        session.commit()

        if is_ci:
            # create CI version with git hash suffix
            info.origversion = info.version
            if is_ci:
                info.version += "+git{}.{}".format(info.tag_dt.strftime("%Y%m%d%H%M%S"), git_ref[:6])

            # check if CI builds enabled in any project version
            found = False
            for target in targets:
                projectversion = session.query(ProjectVersion).filter(
                        ProjectVersion.ci_builds_enabled == True,  # noqa: E712
                        ProjectVersion.id == target.projectversion_id).first()
                if projectversion:
                    found = True
                    break
            if not found:
                repo.log_state("CI builds not enabled in specified projectversions, not building...")
                write_log(parent_build_id, "E: CI builds not enabled in specified projectversions, not building...\n")
                write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
                await parent.set_successful()
                repo.set_ready()
                session.commit()
                return

        # Check if source build already exists
        build = session.query(Build).filter(Build.buildtype == "source",
                                            Build.sourcerepository == repo,
                                            Build.version == info.version).first()
        if build:
            repo.log_state("source package already built for version {}".format(info.version))
            write_log(parent_build_id, "E: source package already built for version {}\n".format(info.version))
            write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            repo.set_ready()
            await parent.set_successful()
            session.commit()
            args = {"schedule": []}
            await task_queue.put(args)
            return

        # Use commiter name as maintainer for CI builds
        if is_ci:
            t = info.author_name.split(" ", 2)
            if len(t) == 2:
                firstname = t[0]
                lastname = t[1]
            else:
                firstname = t[0]
                lastname = ""
            email = info.author_email
        else:
            firstname = info.firstname
            lastname = info.lastname
            email = info.email

        maintainer = session.query(Maintainer).filter(Maintainer.email == email).first()
        if not maintainer:
            repo.log_state("creating new maintainer: %s %s <%s>" % (firstname, lastname, email))
            write_log(parent_build_id, "I: creating new maintainer: %s %s <%s>\n" % (firstname, lastname, email))
            maintainer = Maintainer(firstname=firstname, surname=lastname, email=email)
            session.add(maintainer)
            session.commit()

        # FIXME: assert version == git tag

        build = Build(
            version=info.version,
            git_ref=info.commit_hash,
            ci_branch=ci_branch,
            is_ci=is_ci,
            versiontimestamp=info.tag_stamp,
            sourcename=info.sourcename,
            buildstate="new",
            buildtype="source",
            buildconfiguration=None,
            parent_id=parent_build_id,
            sourcerepository=repo,
            maintainer=maintainer,
        )

        # update patent
        parent.version = info.version
        parent.sourcerepository = repo
        parent.maintainer = maintainer
        parent.git_ref = info.commit_hash

        session.add(build)
        session.commit()
        build.log_state("created")
        await parent.build_changed()
        await build.build_added()

        # add build order dependencies
        build_after = get_buildorder(repo.src_path)
        if build_after:
            logger.info("build after %s", build_after)
            build.builddeps = "{" + ",".join(build_after) + "}"
            session.commit()

        projectversion_ids = []
        build_configs = get_buildconfigs(targets, session)
        found = False
        for build_config in build_configs:
            projectversion_ids.extend([projectversion.id for projectversion in build_config.projectversions])
            # FIXME: filter for buildtype?
            deb_build = session.query(Build).filter(
                            Build.buildconfiguration == build_config,
                            Build.versiontimestamp == info.tag_stamp,
                            Build.version == info.version).first()
            if deb_build:
                logger.warning("already built %s", repo.name)
                write_log(parent_build_id, "E: already built {}\n".format(repo.name))
                continue

            # FIXME: why projectversion[0] ??
            if build_config.projectversions[0].is_locked:
                repo.log_state("build to locked projectversion '%s-%s' not permitted" % (
                        build_config.projectversions[0].project.name,
                        build_config.projectversions[0].name,
                    ))
                write_log(parent_build_id, "W: build to locked projectversion '%s-%s' not permitted\n" % (
                        build_config.projectversions[0].project.name,
                        build_config.projectversions[0].name,
                    ))
                continue

            if is_ci and not build_config.projectversions[0].ci_builds_enabled:
                repo.log_state("CI builds not enabled in projectversion '%s-%s'" % (
                        build_config.projectversions[0].project.name,
                        build_config.projectversions[0].name,
                    ))
                write_log(parent_build_id, "W: CI builds not enabled in projectversion '%s-%s'\n" % (
                        build_config.projectversions[0].project.name,
                        build_config.projectversions[0].name,
                    ))
                continue

            found = True

            write_log(parent_build_id, "I: creating build for projectversion '%s/%s'\n" % (
                    build_config.projectversions[0].project.name,
                    build_config.projectversions[0].name,
                ))

            deb_build = Build(
                version=info.version,
                git_ref=info.commit_hash,
                ci_branch=ci_branch,
                is_ci=is_ci,
                versiontimestamp=info.tag_stamp,
                sourcename=info.sourcename,
                buildstate="new",
                buildtype="deb",
                buildconfiguration=build_config,
                parent_id=build.id,
                sourcerepository=repo,
                maintainer=maintainer,
            )

            session.add(deb_build)
            session.commit()

            deb_build.log_state("created")
            await deb_build.build_added()

        # FIXME: if not found, abort?

        session.commit()

        # make list unique, filter duplicates (multiple archs)
        projectversion_ids = list(set(projectversion_ids))

        await build.set_building()
        session.commit()

        write_log(parent_build_id, "I: building source package\n")

        async def fail():
            write_log(parent_build_id, "E: building source package failed\n")
            write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)
            repo.set_ready()
            await build.set_failed()
            session.commit()
            # FIXME: cancel deb builds, or only create deb builds after source build ok

        # Build Source Package
        write_log_title(build.id, "Source Build")
        try:
            ret = await BuildDebSrc(repo_id, repo.src_path, build.id, info.version, is_ci,
                                    "{} {}".format(firstname, lastname), email)
        except Exception as exc:
            logger.exception(exc)
            await fail()
            return

        if not ret:
            await fail()
            return

        await build.set_needs_publish()
        session.commit()

        repo.set_ready()
        session.commit()

        write_log(parent_build_id, "I: publishing source package\n")
        await aptly_queue.put({"src_publish": [build.id, projectversion_ids]})


def chroot_ready(build, session):
    """
    Checks if the needed chroot
    for the given build is ready.
    Creates the chroot if it is not ready.

    Args:
        build (molior.model.build.Build): The build to check.

    Returns:
        bool: True if chroot ready, otherwise False.
    """
    target_arch = get_target_arch(build, session)

    buildvar = build.buildconfiguration.buildvariant
    if buildvar.architecture.name == "all":
        buildvar = (
            session.query(BuildVariant)
            .join(Architecture)
            .filter(BuildVariant.base_mirror == buildvar.base_mirror)
            .filter(Architecture.name == target_arch)
            .first()
        )

    chroot = session.query(Chroot).filter(Chroot.buildvariant == buildvar).first()
    if chroot:
        if chroot.ready:
            return True

    build.log_state("chroot not ready")
    return False


async def schedule_build(build, session):
    """
    Sends the given build to
    the task queue.

    Args:
        build (molior.model.build.Build): Build to schedule.
    """
    if not chroot_ready(build, session):
        return False

    token = uuid.uuid4()
    buildtask = BuildTask(build=build, task_id=str(token))
    session.add(buildtask)
    session.commit()

    arch = build.buildconfiguration.buildvariant.architecture.name
    base_mirror_db = build.buildconfiguration.buildvariant.base_mirror
    distrelease_name = base_mirror_db.project.name
    distrelease_version = base_mirror_db.name

    # FIXME: why [0] ?
    project_version = build.buildconfiguration.projectversions[0]
    apt_urls = get_apt_repos(project_version, session, is_ci=build.is_ci)

    arch_any_only = False if arch == get_target_arch(build, session) else True

    config = Configuration()
    apt_url = config.aptly.get("apt_url")

    token = buildtask.task_id

    await build.set_scheduled()
    session.commit()  # pylint: disable=no-member

    await backend_queue.put(
        {
            "schedule": [
                build.id,
                token,
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
        }
    )
    return True


def get_apt_repos(project_version, session, is_ci=False):
    """
    Returns a list of all needed apt sources urls
    for the given project_version.

    Args:
        base_mirror (str): The base mirror name ("jessie-8.9").
        projectversion (ProjectVersion): The project_version.
        distribution (str): The distribution

    Returns:
        list: List of apt urls.
    """
    dep_ids = get_projectversion_deps(project_version.id, session)
    deps = session.query(ProjectVersion).filter(ProjectVersion.id.in_(set(dep_ids))).all()

    urls = []

    if is_ci:
        urls.append(project_version.get_apt_repo(dist="unstable"))

    urls.append(project_version.get_apt_repo())
    for project_ver in deps:
        urls.append(project_ver.get_apt_repo())

    return urls


async def ScheduleBuilds():

    logger.info("scheduler: checking for pending builds")

    with Session() as session:

        needed_builds = session.query(Build).filter(Build.buildstate == "needs_build", Build.buildtype == "deb").all()
        for build in needed_builds:
            if not chroot_ready(build, session):
                continue

            repo_deps = []
            if build.parent.builddeps:
                builddeps = build.parent.builddeps[1:-1].split(",")
                for builddep in builddeps:
                    repo_dep = session.query(SourceRepository).filter(SourceRepository.projectversions.any(
                                             id=build.projectversion_id)).filter(or_(
                                                SourceRepository.url == builddep,
                                                SourceRepository.url.like("%/{}".format(builddep)),
                                                SourceRepository.url.like("%/{}.git".format(builddep)))).first()

                    repo_deps.append(repo_dep.id)

            if not repo_deps:
                # build.log_state("scheduler: no build order dependencies, scheduling...")
                await schedule_build(build, session)
                break

            ready = True
            for dep_repo_id in repo_deps:
                dep_repo = session.query(SourceRepository).filter(SourceRepository.id == dep_repo_id).first()
                if not dep_repo:
                    logger.warning("scheduler: repo %d not found", dep_repo_id)
                    continue

                # FIXME: buildconfig arch dependent!

                # find running builds in the same projectversion
                found_running = False

                # check no build order dep is needs_build, building, publishing, ...
                # FIXME: this needs maybe checking of source packages as well?
                running_builds = session.query(Build).filter(or_(
                            Build.buildstate == "new",
                            Build.buildstate == "needs_build",
                            Build.buildstate == "scheduled",
                            Build.buildstate == "building",
                            Build.buildstate == "needs_publish",
                            Build.buildstate == "publishing",
                        ), Build.buildtype == "build",
                        Build.sourcerepository_id == dep_repo_id,
                        Build.projectversion_id == build.projectversion_id).all()

                if running_builds:
                    found_running = True

                    projectversion = session.query(ProjectVersion).filter(
                            ProjectVersion.id == build.projectversion_id).first()
                    if not projectversion:
                        pvname = "unknown"
                        logger.warning("scheduler: projectversion %d not found", build.projectversion_id)
                    else:
                        pvname = projectversion.fullname
                    builds = [str(b.id) for b in running_builds]
                    write_log(build.id, "W: waiting for repo {} to finish building ({}) in projectversion {}\n".format(
                                         dep_repo.name, ", ".join(builds), pvname))
                    break

                if found_running:
                    ready = False
                    break

                # find successful builds in the same and dependent projectversions
                found = False
                successful_builds = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "build",
                        Build.sourcerepository_id == dep_repo_id,
                        Build.projectversion_id == build.projectversion_id).all()

                if successful_builds:
                    found = True

                if not found:
                    ready = False
                    projectversion = session.query(ProjectVersion).filter(
                            ProjectVersion.id == build.projectversion_id).first()
                    if not projectversion:
                        pvname = "unknown"
                        logger.warning("scheduler: projectversion %d not found", build.projectversion_id)
                    else:
                        pvname = projectversion.fullname

                    write_log(build.id, "W: waiting for repo {} to be built in projectversion {}\n".format(
                                         dep_repo.name, pvname))
                    break

            if ready:
                # build.log_state("scheduler: found all required build order dependencies, scheduling...")
                await schedule_build(build, session)
