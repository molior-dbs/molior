import shutil
import shlex
import operator

from launchy import Launchy
from datetime import datetime

from molior.app import logger
from molior.model.database import Session
from molior.model.sourcerepository import SourceRepository
from molior.model.build import Build
from molior.molior.buildlogger import write_log, write_log_title
from molior.molior.errors import MaintainerParseError
from molior.molior.core import get_maintainer, get_target_config
from molior.tools import get_changelog_attr, validate_version_format


async def run_git(cmd, cwd, build_id):

    async def outh(line):
        write_log(build_id, "%s\n" % line)

    process = Launchy(shlex.split(cmd), outh, outh, cwd=cwd)
    await process.launch()
    return await process.wait()


async def GitClone(build_id, repo_id, task_queue):

    with Session() as session:
        repo = (
            session.query(SourceRepository)
            .filter(SourceRepository.id == repo_id)
            .first()
        )

        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("BuildProcess: build %d not found", build_id)
            return

        repo.set_busy()
        session.commit()

        write_log_title(build_id, "Clone Respository")
        logger.info("cloning repository '%s' into '%s'", repo.url, str(repo.src_path))
        write_log(build_id, "I: cloning repository '{}'\n".format(repo.url))

        if not repo.path.exists():
            repo.path.mkdir()

        if repo.src_path.exists():
            logger.info("clone task: removing git repo %s", str(repo.src_path))
            shutil.rmtree(str(repo.src_path))

        ret = await run_git("git clone --config http.sslVerify=false {}".format(repo.url), str(repo.path), build_id)
        if ret != 0:
            logger.error("error running git clone")
            repo.set_error()
            await build.set_failed()
            session.commit()
            return

        git_commands = ["git config http.sslverify false", "git lfs install"]
        for git_command in git_commands:
            ret = await run_git(git_command, str(repo.src_path), build_id)
            if ret != 0:
                logger.error("error running git command: %s", git_command)
                return

        write_log(build_id, "\n")

        repo.set_ready()
        session.commit()

        args = {"buildlatest": [repo.id, build_id]}
        await task_queue.put(args)


async def GitCheckout(src_repo_path, git_ref, build_id):

    git_commands = ["git fetch --tags --force",
                    "git reset --hard",
                    "git clean -dffx",
                    "git checkout --force {}".format(git_ref),
                    "git submodule sync --recursive",
                    "git submodule update --init --recursive",
                    "git clean -dffx",
                    "git lfs pull"]

    for git_command in git_commands:
        ret = await run_git(git_command, str(src_repo_path), build_id)
        if ret != 0:
            logger.error("error running git command: %s", git_command)
            return False

    return True


async def get_latest_tag(path, build_id):
    """
    Returns latest tag from given git
    repository.

    Args:
        path (str): Path to git repository

    Returns:
        tag (Git.tag): The latest git tag
    """
    ret = await run_git("git fetch --tags --force", str(path), build_id)
    if ret != 0:
        logger.error("error running git fetch: %s", str(path))
        return None

    git_tags = []

    async def outh(line):
        nonlocal git_tags
        git_tags.append(line.strip())

    process = Launchy(shlex.split("git tag"), outh, outh, cwd=str(path))
    await process.launch()
    await process.wait()

    valid_tags = {}

    # get commit timestamps
    for tag in git_tags:
        timestamp = None

        async def outh2(line):
            nonlocal timestamp
            timestamp = line.strip()

        process = Launchy(shlex.split("git show -s --format=%ct {}".format(tag)), outh2, outh2, cwd=str(path))
        await process.launch()
        await process.wait()

        if timestamp and validate_version_format(tag):
            valid_tags[timestamp] = tag

    if valid_tags:
        return max(valid_tags.items(), key=operator.itemgetter(0))[1]
    return None


async def GetBuildInfo(repo_path, git_ref):
    class BuildInfo:
        pass

    info = BuildInfo()
    info.version = await get_changelog_attr("Version", repo_path)
    info.sourcename = await get_changelog_attr("Source", repo_path)

    gitinfo = None

    async def outh(line):
        nonlocal gitinfo
        gitinfo = line.strip()

    process = Launchy(shlex.split("git show -s --format='%H %cI %ae %an'"), outh, outh, cwd=str(repo_path))
    await process.launch()
    await process.wait()

    gitinfos = gitinfo.split(" ", 3)
    if len(gitinfos) != 4:
        logger.error("Error parsing git info '%s'", gitinfos)
        return None

    info.commit_hash = gitinfos[0]
    d = gitinfos[1]
    info.author_email = gitinfos[2]
    info.author_name = gitinfos[3]

    ts = d[0:19] + d[19:25].replace(":", "")
    tag_dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")

    info.tag_stamp = tag_dt.strftime("%Y-%m-%d %T%z")
    info.tag_dt = tag_dt

    try:
        info.firstname, info.lastname, info.email = await get_maintainer(repo_path)
    except MaintainerParseError as exc:
        logger.warning("could not get maintainer: %s" % str(exc))
        return None

    info.plain_targets = get_target_config(repo_path)

    return info
