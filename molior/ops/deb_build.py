import asyncio
import uuid
import os
import re
import aiohttp

from launchy import Launchy
from sqlalchemy import or_
from pathlib import Path
from datetime import datetime
from aiofile import AIOFile, Writer
from tempfile import mkdtemp
from shutil import rmtree

from ..app import logger
from ..tools import get_changelog_attr, strip_epoch_version, db2array, array2db
from .git import GitCheckout, GetBuildInfo

from ..model.database import Session
from ..model.sourcerepository import SourceRepository
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.maintainer import Maintainer
from ..model.chroot import Chroot
from ..model.projectversion import ProjectVersion
from ..molior.core import get_target_arch, get_targets, get_buildorder, get_apt_repos, get_apt_keys
from ..molior.configuration import Configuration
from ..molior.queues import enqueue_task, enqueue_aptly, enqueue_backend, buildlog, buildlogtitle, buildlogdone


async def BuildDebSrc(repo_id, repo_path, build_id, ci_version, is_ci, author, email):
    await buildlog(build_id, "I: getting debian build information\n")
    src_package_name = await get_changelog_attr("Source", repo_path)
    version = await get_changelog_attr("Version", repo_path)
    repo_path = Path(repo_path)

    # FIXME: use global var
    key = Configuration().debsign_gpg_email
    if not key:
        await buildlog(build_id, "E: Signing key not defined in configuration\n")
        logger.error("Signing key not defined in configuration")
        return False

    async def outh(line):
        line = line.strip()
        if line:
            await buildlog(build_id, "%s\n" % line)

    if is_ci:
        # in order to publish a sourcepackage for a ci build we need
        # to create a ci changelog with the correct version

        distribution = await get_changelog_attr("Distribution", repo_path)

        env = os.environ.copy()
        env["DEBFULLNAME"] = author
        env["DEBEMAIL"] = email
        dchcmd = "dch -v %s --distribution %s --force-distribution 'CI Build'" % (ci_version, distribution)
        version = ci_version

        process = Launchy(dchcmd, outh, outh, cwd=str(repo_path), env=env)
        await process.launch()
        ret = await process.wait()
        if ret != 0:
            logger.error("Error running dch for CI build")
            return False

        if (repo_path / ".git").exists():
            process = Launchy("git -c user.name='{}' -c user.email='{}' commit -a -m 'ci build'".format(author, email),
                              outh, outh, cwd=str(repo_path))
            await process.launch()
            ret = await process.wait()
            if ret != 0:
                logger.error("Error creating ci build commit")
                return False

    logger.debug("%s: creating source package", src_package_name)
    await buildlog(build_id, "I: creating source package: %s (%s)\n" % (src_package_name, version))

    cmd = "dpkg-buildpackage -S -d -nc -I.git -pgpg1 -k{}".format(key)
    process = Launchy(cmd, outh, outh, cwd=str(repo_path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        await buildlog(build_id, "E: Error building source package\n")
        logger.error("source packaging failed, dpkg-builpackage returned %d", ret)
        return False

    logger.debug("%s (%d): source package v%s created", src_package_name, repo_id, version)
    return True


async def DownloadDebSrc(repo_id, sourcename, build_id, version, basemirror, projectversion):
    await buildlogtitle(build_id, "Source Package Republish")
    await buildlog(build_id, "I: downloading source package from {} ({})\n".format(projectversion, basemirror))
    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url")
    sources_url = "{}/{}/repos/{}/dists/stable/main/source/Sources".format(apt_url, basemirror, projectversion)

    # download Sources file
    Sources = ""
    async with aiohttp.ClientSession() as http:
        async with http.get(sources_url) as resp:
            if not resp.status == 200:
                await buildlog(build_id, "E: Error downloading {}\n".format(sources_url))
                return False
            Sources = await resp.text()

    if not Sources:
        await buildlog(build_id, "E: Invalid Sources file: {}\n".format(sources_url))
        return False

    # parse Soures file
    files = []
    directory = None
    found_package_entry = False
    found_directory_entry = False
    found_files_section = False
    for line in Sources.split('\n'):
        if not found_package_entry:
            if line != "Package: {}".format(sourcename):
                continue
            found_package_entry = True
            continue
        else:  # Package section
            if not found_directory_entry:
                if line == "":
                    break
                if not line.startswith("Directory: "):
                    continue
                found_directory_entry = True
                directory = line.split(" ")[1]
                continue
            elif not found_files_section:
                if line == "":
                    break
                if line != "Files:":
                    continue
                found_files_section = True
                continue
            else:  # Files section
                if line.startswith(" "):
                    files.append(line[1:].split(" "))
                else:
                    break

    if not found_directory_entry:
        await buildlog(build_id, "E: Could not find {}/{} in Sources file: {}\n".format(sourcename, version, sources_url))
        return False

    await buildlog(build_id, "I: found directory: {}\n".format(directory))
    await buildlog(build_id, "I: downloading source files:\n")
    sourcefile = None
    sourcetype = None
    for f in files:
        await buildlog(build_id, " - {}\n".format(f[2]))

        file_url = "{}/{}/repos/{}/{}/{}".format(apt_url, basemirror, projectversion, directory, f[2])
        body = None
        async with aiohttp.ClientSession() as http:
            async with http.get(file_url) as resp:
                if not resp.status == 200:
                    await buildlog(build_id, "E: Error downloading {}\n".format(file_url))
                    return False
                body = await resp.read()

        filepath = "/var/lib/molior/repositories/{}/{}".format(repo_id, f[2])
        async with AIOFile(filepath, "wb") as afp:
            writer = Writer(afp)
            await writer(body)

        if filepath.endswith(".git"):
            sourcetype = "git"
            sourcefile = filepath
        elif filepath.endswith(".tar.gz") or filepath.endswith(".tar.xz"):
            sourcetype = "tar"
            sourcefile = filepath

    # extract source, if git, checkout version tag
    ret = None
    if sourcetype:
        tmpdir = mkdtemp(dir="/var/lib/molior/repositories/{}/".format(repo_id))
        output = ""

        async def outh(line):
            nonlocal output
            await buildlog(build_id, "{}\n".format(line))
            output += line

        if sourcetype == "tar":
            cmd = "tar xf {}".format(sourcefile)
            await buildlog(build_id, "$ {}\n".format(cmd))
            process = Launchy(cmd, outh, outh, cwd=tmpdir)
            await process.launch()
            ret = await process.wait()
        elif sourcetype == "git":
            cmd = "git clone -b v{} {} .".format(version, filepath)
            await buildlog(build_id, "$ {}\n".format(cmd))
            process = Launchy(cmd, outh, outh, cwd=tmpdir)
            await process.launch()
            ret = await process.wait()
            output = ""

        if ret == 0:
            cmd = "dpkg-genchanges -S"
            await buildlog(build_id, "$ {}\n".format(cmd))
            process = Launchy(cmd, outh, outh, cwd=tmpdir)
            await process.launch()
            ret = await process.wait()

        if ret == 0:
            cmd = "dpkg-genbuildinfo --build=source"
            await buildlog(build_id, "$ {}\n".format(cmd))
            process = Launchy(cmd, outh, outh, cwd=tmpdir)
            await process.launch()
            ret = await process.wait()

        try:
            rmtree(tmpdir)
        except Exception:
            pass

    return ret == 0


async def BuildProcess(parent_build_id, repo_id, git_ref, ci_branch, custom_targets, force_ci=False):
    await buildlogtitle(parent_build_id, "Molior Build")
    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return

        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            await parent.log("E: source repository {} not found\n".format(repo_id))
            await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await parent.logdone()
            await parent.set_failed()
            session.commit()
            return
        src_path = repo.src_path

    await buildlog(parent_build_id, "I: git checkout {}\n".format(git_ref))

    # Checkout
    ret = await asyncio.ensure_future(GitCheckout(src_path, git_ref, parent_build_id))

    if not ret:
        await buildlog(parent_build_id, "E: git checkout failed\n")
        await buildlogtitle(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
        await buildlogdone(parent_build_id)

    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return
        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            return

        if not ret:
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

    await buildlog(parent_build_id, "\nI: get build information\n")

    info = None
    try:
        info = await GetBuildInfo(repo.src_path, git_ref)
    except Exception as exc:
        logger.exception(exc)

    if not info:
        await buildlog(parent_build_id, "E: Error getting build information\n")
        await buildlogtitle(parent_build_id, "Done", no_footer_newline=True, no_header_newline=False)
        await buildlogdone(parent_build_id)

    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return
        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            return

        if not info:
            await parent.set_failed()
            repo.set_ready()
            session.commit()
            return

        targets = get_targets(info.plain_targets, repo, custom_targets, session)

        if not targets:
            repo.log_state("unknown target projectversions in debian/molior.yml")
            await parent.log("E: the repository is not added to any projectversions from debian/molior.yml:\n")
            await parent.log("   %s\n" % str(info.plain_targets))
            await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await parent.logdone()
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

        process = Launchy("git describe --tags --abbrev=40", outh, outh, cwd=str(src_path))
        await process.launch()
        ret = await process.wait()
        if ret != 0:
            logger.error("error running git describe: %s" % gittag.strip())
        else:
            v = strip_epoch_version(info.version)
            if not re.match("^v?{}$".format(v.replace("~", "-").replace("+", "\\+")), gittag) or "+git" in v:
                is_ci = True

    ci_cfg = Configuration().ci_builds
    ci_enabled = ci_cfg.get("enabled") if ci_cfg else False

    with Session() as session:
        parent = session.query(Build).filter(Build.id == parent_build_id).first()
        if not parent:
            logger.error("BuildProcess: parent build {} not found".format(parent_build_id))
            return
        repo = session.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            return

        if is_ci and not ci_enabled:
            repo.log_state("CI builds are not enabled in configuration")
            await parent.log("E: CI builds are not enabled in configuration\n")
            await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await parent.logdone()
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
                        ProjectVersion.ci_builds_enabled.is_(True),
                        ProjectVersion.id == target.projectversion_id).first()
                if projectversion:
                    found = True
                    break
            if not found:
                repo.log_state("CI builds not enabled in specified projectversions, not building...")
                await parent.log("E: CI builds not enabled in specified projectversions, not building...\n")
                await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
                await parent.logdone()
                await parent.set_nothing_done()
                repo.set_ready()
                session.commit()
                return

        missing_builds = False
        # Check if source build already exists
        existing_src_build = session.query(Build).filter(Build.buildtype == "source",
                                                         Build.sourcerepository == repo,
                                                         Build.version == info.version,
                                                         Build.buildstate == "successful").first()
        if existing_src_build:
            # check for missing successful deb builds
            for target in targets:
                for arch in db2array(target.architectures):
                    # FIXME: check buildstates
                    deb_build = session.query(Build).filter(Build.buildtype == "deb",
                                                            Build.sourcerepository == repo,
                                                            Build.version == info.version,
                                                            Build.projectversion_id == target.projectversion_id,
                                                            Build.architecture == arch).first()
                    if not deb_build:
                        missing_builds = True

            if not missing_builds:
                await parent.log("E: all debian builds already existing for version {}\n".format(info.version))
                await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
                await parent.logdone()
                repo.set_ready()
                if existing_src_build.parent and existing_src_build.parent.buildstate == "successful":
                    await parent.set_already_exists()
                else:
                    await parent.set_already_failed()
                session.commit()
                args = {"schedule": []}
                await enqueue_task(args)
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
        await parent.build_changed()
        await build.build_added()

        # add build order dependencies
        build_after = get_buildorder(repo.src_path)
        if build_after:
            await build.parent.log("N: source needs to build after: %s\n" % ", ".join(build_after))
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
                await parent.log("W: build to locked projectversion '%s-%s' not permitted\n" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                continue

            if is_ci and not projectversion.ci_builds_enabled:
                repo.log_state("CI builds not enabled in projectversion '%s-%s'" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                await parent.log("W: CI builds not enabled in projectversion '%s-%s'\n" % (
                        projectversion.project.name,
                        projectversion.name,
                    ))
                continue

            architectures = db2array(target.architectures)
            for architecture in architectures:
                deb_build = session.query(Build).filter(
                                Build.sourcerepository_id == repo.id,
                                Build.projectversion == projectversion,
                                Build.version == info.version,
                                Build.buildtype == "deb",
                                Build.architecture == architecture).first()
                if deb_build:
                    if deb_build.buildstate != "successful":
                        deb_build.buildstate = "needs_build"
                        session.commit()
                        found = True  # FIXME: should this be here ?
                        continue
                    await parent.log("W: packages already built for {} {}\n".format(projectversion.fullname, architecture))
                    continue

                found = True

                # only add projectversions where a debian package will be built.
                # this allows deleting a source republish without deleting the original source package
                if projectversion.id not in projectversion_ids:
                    projectversion_ids.append(projectversion.id)

                await parent.log("I: creating build for projectversion '%s/%s'\n" % (
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

                await deb_build.build_added()

        if not found:
            await parent.log("E: no projectversion found to build for")
            await parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await parent.logdone()
            await parent.set_nothing_done()
            repo.set_ready()
            session.commit()
            return

        build.projectversions = array2db([str(p) for p in projectversion_ids])
        session.commit()

        build_id = build.id

    await enqueue_task({"src_build": [build_id]})


async def BuildSourcePackage(build_id):
    source_exists = False
    with Session() as db:
        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("BuildProcess: build {} not found".format(build_id))
            return
        parent_build_id = build.parent_id
        repo_id = build.sourcerepository_id
        src_path = build.sourcerepository.src_path
        version = build.version
        is_ci = build.is_ci
        firstname = build.maintainer.firstname
        lastname = build.maintainer.surname
        email = build.maintainer.email

        await build.set_building()
        db.commit()

        src_build = db.query(Build).filter(Build.sourcerepository_id == repo_id,
                                           Build.version == version,
                                           Build.buildtype == "source",
                                           Build.buildstate == "successful",
                                           Build.is_deleted.is_(False)).first()
        if src_build:
            projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == src_build.projectversions[0]).first()
            if projectversion:
                basemirror = projectversion.basemirror.fullname
                projectversion = projectversion.fullname
                sourcename = src_build.sourcename
                source_exists = True

        if source_exists:
            await build.parent.log("I: downloading source package\n")
        else:
            await build.parent.log("I: building source package\n")
            await build.logtitle("Source Build")

    async def fail():
        with Session() as db:
            build = db.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("BuildProcess: build {} not found".format(build_id))
                return
            parent = db.query(Build).filter(Build.id == build.parent_id).first()
            if not parent:
                logger.error("BuildProcess: parent build {} not found".format(build.parent_id))
                return
            repo = db.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
            if not repo:
                logger.error("source repository %d not found", repo_id)
                return

            if source_exists:
                await parent.log("E: downloading source package failed\n")
            else:
                await parent.log("E: building source package failed\n")
            await build.logtitle("Done", no_footer_newline=True, no_header_newline=True)
            await parent.logtitle("Done", no_footer_newline=True, no_header_newline=True)
            await parent.logdone()
            repo.set_ready()
            await build.set_failed()
            db.commit()
            # FIXME: cancel deb builds, or only create deb builds after source build ok

    try:
        if not source_exists:
            ret = await BuildDebSrc(repo_id, src_path, build_id, version, is_ci,
                                    "{} {}".format(firstname, lastname), email)
        else:
            ret = await DownloadDebSrc(repo_id, sourcename, build_id, version, basemirror, projectversion)
    except Exception as exc:
        logger.exception(exc)
        await fail()
        return

    if not ret:
        await fail()
        return

    with Session() as db:
        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("BuildProcess: build {} not found".format(build_id))
            return
        repo = db.query(SourceRepository) .filter(SourceRepository.id == repo_id) .first()
        if not repo:
            logger.error("source repository %d not found", repo_id)
            return

        await build.set_needs_publish()
        db.commit()

        repo.set_ready()
        db.commit()

    await buildlog(parent_build_id, "I: publishing source package\n")
    await enqueue_aptly({"src_publish": [build_id]})


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
    chroot = session.query(Chroot).filter(Chroot.basemirror_id == build.projectversion.basemirror_id,
                                          Chroot.architecture == target_arch).first()
    if not chroot:
        build.log_state("chroot not found")
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
    apt_keys = get_apt_keys(project_version, session)

    arch_any_only = False if arch == get_target_arch(build, session) else True

    config = Configuration()
    apt_url = config.aptly.get("apt_url")

    token = buildtask.task_id

    run_lintian = True
    if build.is_ci:
        run_lintian = False

    await build.set_scheduled()
    session.commit()

    await enqueue_backend(
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
                apt_keys,
                run_lintian
            ]
        }
    )
    return True


def get_dependencies_recursive(dependencies, array):
    for dep in dependencies:
        if dep.project.is_mirror:
            continue
        if dep.id not in array:
            array.append(dep.id)
        get_dependencies_recursive(dep.dependencies, array)


async def ScheduleBuilds():
    with Session() as session:

        needed_builds = session.query(Build).filter(Build.buildstate == "needs_build", Build.buildtype == "deb").all()
        for build in needed_builds:
            if not chroot_ready(build, session):
                continue

            projectversion = session.query(ProjectVersion).filter(
                    ProjectVersion.id == build.projectversion_id).first()
            if not projectversion:
                logger.warning("scheduler: projectversion %d not found", build.projectversion_id)
                continue

            pvname = projectversion.fullname
            buildorder_projectversions = [build.projectversion_id]
            get_dependencies_recursive(projectversion.dependencies, buildorder_projectversions)
#            for dep in projectversion.dependencies:
#                if dep.project.is_mirror:
#                    continue
#                buildorder_projectversions.append(dep.id)

            ready = True
            repo_deps = []
            if build.parent.builddeps:
                builddeps = build.parent.builddeps
                for builddep in builddeps:
                    repo_dep = None
                    for buildorder_projectversion in buildorder_projectversions:
                        repo_dep = session.query(SourceRepository).filter(SourceRepository.projectversions.any(
                                                 id=buildorder_projectversion)).filter(or_(
                                                    SourceRepository.url == builddep,
                                                    SourceRepository.url.like("%/{}".format(builddep)),
                                                    SourceRepository.url.like("%/{}.git".format(builddep)))).first()
                        if repo_dep:
                            break

                    if not repo_dep:
                        logger.error("build-{}: dependency {} not found in projectversion {}".format(build.id,
                                     builddep, build.projectversion_id))
                        await build.log("E: dependency {} not found in projectversion {} nor dependencies\n".format(
                                             builddep, pvname))
                        ready = False
                        break
                    repo_deps.append(repo_dep.id)

            if not ready:
                continue

            if not repo_deps:
                # build.log_state("scheduler: no build order dependencies, scheduling...")
                await schedule_build(build, session)
                continue

            for dep_repo_id in repo_deps:
                dep_repo = session.query(SourceRepository).filter(SourceRepository.id == dep_repo_id).first()
                if not dep_repo:
                    logger.warning("scheduler: repo %d not found", dep_repo_id)
                    continue

                # FIXME: buildconfig arch dependent!

                # find running builds in the same projectversion
                # FIXME: check also dependencies which are not mirrors

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
                        Build.projectversion_id.in_(buildorder_projectversions)).all()

                if running_builds:
                    ready = False
                    builds = [str(b.id) for b in running_builds]
                    await build.log("W: waiting for repo {} to finish building ({}) in projectversion {} or dependencies\n".
                                    format(dep_repo.name, ", ".join(builds), pvname))
                    continue

                # find successful builds in the same and dependent projectversions
                # FIXME: search same architecture as well
                found = False
                successful_builds = session.query(Build).filter(
                        Build.buildstate == "successful",
                        Build.buildtype == "deb",
                        Build.sourcerepository_id == dep_repo_id,
                        Build.projectversion_id.in_(buildorder_projectversions))
                successful_builds = successful_builds.all()

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

                    await build.log("W: waiting for repo {} to be built in projectversion {} or dependencies\n".format(
                                         dep_repo.name, pvname))
                    continue

            if ready:
                # build.log_state("scheduler: found all required build order dependencies, scheduling...")
                await schedule_build(build, session)
