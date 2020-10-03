import asyncio
import shlex
import uuid
import os
import re

from launchy import Launchy
from sqlalchemy import or_
from pathlib import Path
from datetime import datetime

from ..app import logger
from ..tools import get_changelog_attr, strip_epoch_version, write_log, write_log_title, db2array
from .git import GitCheckout, GetBuildInfo

from ..model.database import Session
from ..model.sourcerepository import SourceRepository
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.maintainer import Maintainer
from ..model.chroot import Chroot
from ..model.projectversion import ProjectVersion
from ..molior.core import get_target_arch, get_targets, get_buildorder, get_apt_repos
from ..molior.configuration import Configuration
from ..molior.worker_backend import backend_queue


async def BuildDebSrc(repo_id, repo_path, build_id, ci_version, is_ci, author, email):
    await write_log(build_id, "I: getting debian build information\n")
    src_package_name = await get_changelog_attr("Source", repo_path)
    version = await get_changelog_attr("Version", repo_path)
    repo_path = Path(repo_path)

    # FIXME: use global var
    key = Configuration().debsign_gpg_email
    if not key:
        await write_log(build_id, "E: Signing key not defined in configuration\n")
        logger.error("Signing key not defined in configuration")
        return False

    logger.debug("%s: creating source package", src_package_name)
    await write_log(build_id, "I: creating source package: %s (%s)\n" % (src_package_name, version))

    async def outh(line):
        line = line.strip()
        if line:
            await write_log(build_id, "%s\n" % line)

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

        if (repo_path / ".git").exists():
            process = Launchy(shlex.split("git commit -a --author '{} <{}>' -m 'ci build'".format(author, email)),
                              outh, outh, cwd=str(repo_path))
            await process.launch()
            ret = await process.wait()
            if ret != 0:
                logger.error("Error creating ci build commit")
                return False

    cmd = "dpkg-buildpackage -S -d -nc -I.git -pgpg1 -k{}".format(key)
    process = Launchy(shlex.split(cmd), outh, outh, cwd=str(repo_path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        await write_log(build_id, "E: Error building source package\n")
        logger.error("source packaging failed, dpkg-builpackage returned %d", ret)
        return False

    logger.debug("%s (%d): source package v%s created", src_package_name, repo_id, version)
    return True


async def BuildProcess(task_queue, aptly_queue, parent_build_id, repo_id, git_ref, ci_branch, custom_targets, force_ci=False):
    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return

        await write_log_title(parent_build_id, "Molior Build")

        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            await write_log(parent_build_id, "E: source repository {} not found\n".format(repo_id))
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            session.commit()
            return

        await write_log(parent_build_id, "I: git checkout {}\n".format(git_ref))

        # Checkout
        ret = await asyncio.ensure_future(GitCheckout(repo.src_path, git_ref, parent_build_id))
        if not ret:
            await write_log(parent_build_id, "E: git checkout failed\n")
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

        await write_log(parent_build_id, "\nI: get build information\n")
        info = None
        try:
            info = await GetBuildInfo(repo.src_path, git_ref)
        except Exception as exc:
            logger.exception(exc)

        if not info:
            await write_log(parent_build_id, "E: Error getting build information\n")
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

        targets = get_targets(info.plain_targets, repo, custom_targets, session)

        if not targets:
            repo.log_state("unknown target projectversions in debian/molior.yml")
            await write_log(parent_build_id, "E: the repository is not added to any projectversions from debian/molior.yml\n")
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            repo.set_ready()
            await parent.set_nothing_done()
            session.commit()
            return

        is_ci = False
        if force_ci:
            is_ci = True
        else:
            # check if it is a CI build
            # i.e. if gittag does not match version in debian/changelog
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
            await write_log(parent_build_id, "E: CI builds are not enabled in configuration\n")
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_successful()
            repo.set_ready()
            session.commit()
            return

        parent.is_ci = is_ci
        session.commit()

        if is_ci:
            # create CI version with git hash suffix
            info.origversion = info.version
            info.version += "+git{}.{}".format(datetime.now().strftime("%Y%m%d%H%M%S"), info.commit_hash[:6])

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
                await write_log(parent_build_id, "E: CI builds not enabled in specified projectversions, not building...\n")
                await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
                await parent.set_nothing_done()
                repo.set_ready()
                session.commit()
                return

        # Check if source build already exists
        build = session.query(Build).filter(Build.buildtype == "source",
                                            Build.sourcerepository == repo,
                                            Build.version == info.version,
                                            Build.buildstate == "successful").first()
        if build:
            repo.log_state("source package already built for version {}".format(info.version))
            await write_log(parent_build_id, "E: source package already built for version {}\n".format(info.version))
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            repo.set_ready()
            await parent.set_already_exists()
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
            await write_log(parent_build_id, "I: creating new maintainer: %s %s <%s>\n" % (firstname, lastname, email))
            maintainer = Maintainer(firstname=firstname, surname=lastname, email=email)
            session.add(maintainer)
            session.commit()

        # FIXME: assert version == git tag

        build = Build(
            version=info.version,
            git_ref=info.commit_hash,
            ci_branch=ci_branch,
            is_ci=is_ci,
            sourcename=info.sourcename,
            buildstate="new",
            buildtype="source",
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
        found = False
        for target in targets:
            projectversion = session.query(ProjectVersion).filter(ProjectVersion.id == target.projectversion_id).first()
            if projectversion.is_locked:
                repo.log_state("build to locked projectversion '%s-%s' not permitted" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                await write_log(parent_build_id, "W: build to locked projectversion '%s-%s' not permitted\n" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                continue

            if is_ci and not projectversion.ci_builds_enabled:
                repo.log_state("CI builds not enabled in projectversion '%s-%s'" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                await write_log(parent_build_id, "W: CI builds not enabled in projectversion '%s-%s'\n" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                continue

            projectversion_ids.append(projectversion.id)

            architectures = db2array(target.architectures)
            for architecture in architectures:
                deb_build = session.query(Build).filter(
                                Build.projectversion == projectversion,
                                Build.version == info.version,
                                Build.buildtype == "deb",
                                Build.architecture == architecture).first()
                if deb_build:
                    if deb_build.buildstate != "successful":
                        deb_build.buildstate = "needs_build"
                        session.commit()
                        found = True
                        continue
                    logger.warning("already built %s", repo.name)
                    await write_log(parent_build_id, "E: already built {}\n".format(repo.name))
                    continue

                found = True

                await write_log(parent_build_id, "I: creating build for projectversion '%s/%s'\n" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))

                deb_build = Build(
                    version=info.version,
                    git_ref=info.commit_hash,
                    ci_branch=ci_branch,
                    is_ci=is_ci,
                    sourcename=info.sourcename,
                    buildstate="new",
                    buildtype="deb",
                    parent_id=build.id,
                    sourcerepository=repo,
                    maintainer=maintainer,
                    projectversion_id=projectversion.id,
                    architecture=architecture
                )

                session.add(deb_build)
                session.commit()

                deb_build.log_state("created")
                await deb_build.build_added()

        if not found:
            await write_log(parent_build_id, "E: no projectversion found to build for")
            await write_log_title(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await parent.set_nothing_done()
            repo.set_ready()
            session.commit()
            return

        build.projectversions = "{" + ",".join([str(p) for p in projectversion_ids]) + "}"

        await build.set_building()
        session.commit()

        await write_log(parent_build_id, "I: building source package\n")

        async def fail():
            await write_log(parent_build_id, "E: building source package failed\n")
            await write_log_title(build.id, "Done", no_footer_newline=True, no_header_newline=True)
            repo.set_ready()
            await build.set_failed()
            session.commit()
            # FIXME: cancel deb builds, or only create deb builds after source build ok

        # Build Source Package
        await write_log_title(build.id, "Source Build")
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

        await write_log(parent_build_id, "I: publishing source package\n")
        await aptly_queue.put({"src_publish": [build.id]})


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
    target_arch = get_target_arch(build)
    chroot = session.query(Chroot).filter(Chroot.basemirror_id == build.projectversion.basemirror_id,
                                          Chroot.architecture == target_arch).first()
    if not chroot:
        return False
    if not chroot.ready:
        build.log_state("chroot not ready")
        return False
    return True


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

    arch = build.architecture
    distrelease_name = build.projectversion.basemirror.project.name
    distrelease_version = build.projectversion.basemirror.name

    project_version = build.projectversion
    apt_urls = get_apt_repos(project_version, session, is_ci=build.is_ci)

    arch_any_only = False if arch == get_target_arch(build) else True

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


async def ScheduleBuilds():

    logger.info("scheduler: checking for pending builds")

    with Session() as session:

        needed_builds = session.query(Build).filter(Build.buildstate == "needs_build", Build.buildtype == "deb").all()
        for build in needed_builds:
            if not chroot_ready(build, session):
                continue

            repo_deps = []
            if build.parent.builddeps:
                builddeps = build.parent.builddeps
                for builddep in builddeps:
                    repo_dep = session.query(SourceRepository).filter(SourceRepository.projectversions.any(
                                             id=build.projectversion_id)).filter(or_(
                                                SourceRepository.url == builddep,
                                                SourceRepository.url.like("%/{}".format(builddep)),
                                                SourceRepository.url.like("%/{}.git".format(builddep)))).first()

                    if not repo_dep:
                        logger.error("build-{}: dependency {} not found in projectversion {}".format(build.id,
                                     builddep, build.projectversion_id))
                        repo_deps.append(-1)
                        break
                    repo_deps.append(repo_dep.id)

            if not repo_deps:
                # build.log_state("scheduler: no build order dependencies, scheduling...")
                await schedule_build(build, session)
                break

            ready = True
            for dep_repo_id in repo_deps:
                if dep_repo_id == -1:
                    return  # build order dependency not found

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
                        ), Build.buildtype == "deb",
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
                    await write_log(build.id, "W: waiting for repo {} to finish building ({}) in projectversion {}\n".format(
                                         dep_repo.name, ", ".join(builds), pvname))
                    break

                if found_running:
                    ready = False
                    break

                # find successful builds in the same and dependent projectversions
                # FIXME: search same architecture as well
                found = False
                successful_builds = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "deb",
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

                    await write_log(build.id, "W: waiting for repo {} to be built in projectversion {}\n".format(
                                         dep_repo.name, pvname))
                    break

            if ready:
                # build.log_state("scheduler: found all required build order dependencies, scheduling...")
                await schedule_build(build, session)
