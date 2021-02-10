import re

from ..app import logger
from ..tools import get_changelog_attr, db2array
from .configuration import Configuration

from ..model.project import Project
from ..model.sourepprover import SouRepProVer
from ..model.projectversion import ProjectVersion
from ..model.projectversion import get_projectversion_deps


TARGET_ARCH_ORDER = ["amd64", "i386", "arm64", "armhf"]


def get_projectversion(path):
    """
    Reads the projectversion configuration
    from debian/molior.yml

    Args:
        path (str): Path to git repository

    Returns:
        str: The target project_version.

    Examples:
        >>> get_projectversion("/repo/path")
        "1.1"
    """
    config_path = path / "debian" / "molior.yml"
    if not config_path.exists():
        logger.warning("%s: does not exist", str(config_path))
        return str()

    try:
        cfg = Configuration(str(config_path))
        if cfg.config_version:
            return str()

        target_repo_version = cfg.target_repo_version
        if not target_repo_version:
            return str()
    except Exception as exc:
        logger.warning("%s: parse error", str(config_path))
        logger.exception(exc)
        return str()

    if not isinstance(target_repo_version, str):
        logger.warning("%s: 'target_repo_version' is not a string", str(config_path))
        return str()
    return target_repo_version


def get_target_config(path):
    """
    Reads the projectversion configuration
    from debian/molior.yml

    Args:
        path (pathlib.Path): Path to git repository

    Returns:
        list: List of targets.

    Examples:
        >>> get_targets("/repo/path")
        [("myproject", "1.1"), ("myproject2", "1.1")]
    """
    config_path = path / "debian" / "molior.yml"
    if not config_path.exists():
        logger.warning("%s: does not exist", str(config_path))
        return []

    try:
        cfg = Configuration(str(config_path))

        target_repo_version = cfg.config().get("target_repo_version")
        if target_repo_version:
            return [(None, target_repo_version)]

        target_config = cfg.config().get("targets")
    except Exception as exc:
        logger.warning("%s: parse error", str(config_path))
        logger.exception(exc)
        return []

    if not target_config:
        logger.warning("%s: config attribute 'targets'", str(config_path))
        return []

    targets = []

    # in: {"myproject": ["1", "2"]}
    # out: [("myproject", "1"), ("myproject", "2")]
    for project, versions in target_config.items():
        for version in versions:
            targets.append((project, str(version)))
    return list(set(targets))


async def get_maintainer(path):
    """
    Reads maintainer from changelog of given path
    and adds him to the database.

    Args:
        path (Pathlib.Path): Path to git repository.

    Returns:
        tuple (firstname, surname, email)

    """
    full = await get_changelog_attr("Maintainer", path)
    if not full:
        return None
    search = re.search("(.*)<([^>]*)", full)
    if not search:
        return None
    email = search.group(2)
    full_name = search.group(1)
    firstname = full_name.split(" ")[0]
    surname = " ".join(full_name.split(" ")[1:]).strip()

    return (firstname, surname, email)


def get_targets(plain_targets, repo, custom_targets, session):
    """
    Gets the target repo versions and returns them as
    sourcerepositoryprojectversion model objects.

    Args:
        repo (SourceRepository): Source repository model.
    """
    targets = []
    if custom_targets:
        for t in custom_targets:
            try:
                project_name, project_version = t.split("/")
            except Exception as exc:
                logger.exception(exc)
                continue
            targets += (
                session.query(SouRepProVer)
                .join(ProjectVersion)
                .join(Project)
                .filter(SouRepProVer.sourcerepository_id == repo.id)
                .filter(ProjectVersion.name == project_version)
                .filter(Project.name == project_name)
                .all()
            )

    else:
        for target in plain_targets:
            project_name, project_version = target
            targets += (
                session.query(SouRepProVer)
                .join(ProjectVersion)
                .join(Project)
                .filter(SouRepProVer.sourcerepository_id == repo.id)
                .filter(ProjectVersion.name == project_version)
                .filter(Project.name == project_name)
                .all()
            )

    return targets


def get_target_arch(build, session):
    """
    Gets the best target architecture from TARGET_ARCH_ORDER
    for the given build for 'all' packages.

    If a projectversion only supports i386 and armhf, i386 will be
    returned.

    Args:
        build (Build): The build.

    Returns:
        str: The target architecture
    """
    for arch in TARGET_ARCH_ORDER:
        if arch in db2array(build.projectversion.mirror_architectures):
            if build.buildtype == "deb":
                sourepprover = session.query(SouRepProVer).filter(
                        SouRepProVer.sourcerepository_id == build.sourcerepository.id,
                        SouRepProVer.projectversion_id == build.projectversion.id).first()
                if arch not in db2array(sourepprover.architectures):
                    continue
            return arch
    return None


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
    urls = []
    deps = get_projectversion_deps(project_version.id, session)

    urls.append(project_version.get_apt_repo(internal=True))
    if is_ci:
        urls.append(project_version.get_apt_repo(dist="unstable", internal=True))

    for p in deps:
        dependency = session.query(ProjectVersion).filter(ProjectVersion.id == p[0]).first()
        urls.append(dependency.get_apt_repo(internal=True))
        if is_ci and p[1]:  # use unstable dependency for ci builds
            urls.append(dependency.get_apt_repo(dist="unstable", internal=True))

    return urls


def get_apt_keys(project_version, session):
    """
    Returns a list of all needed apt key urls
    for the given project_version.

    Args:
        base_mirror (str): The base mirror name ("jessie-8.9").
        projectversion (ProjectVersion): The project_version.
        distribution (str): The distribution

    Returns:
        list: List of apt urls.
    """
    urls = []
    deps = get_projectversion_deps(project_version.id, session)

    if project_version.external_repo:
        for key in project_version.mirror_keys:
            if key.keyurl:
                if key.keyurl not in urls:
                    urls.append(key.keyurl)
            else:
                logger.error("building with external gog server keys not implemented")

    for p in deps:
        dependency = session.query(ProjectVersion).filter(ProjectVersion.id == p[0]).first()
        if dependency.external_repo:
            for key in dependency.mirror_keys:
                if key.keyurl:
                    if key.keyurl not in urls:
                        urls.append(key.keyurl)
                else:
                    logger.error("building with external gog server keys not implemented")

    return urls


def get_buildorder(path):
    """
    Reads the build order configuration
    from debian/molior.yml

    Args:
        path (pathlib.Path): Path to git repository

    Returns:
        list: List of targets.

    Examples:
        >>> get_buildorder("/repo/path")
        [("myproject", "1.1"), ("myproject2", "1.1")]
    """
    config_path = path / "debian" / "molior.yml"
    if not config_path.exists():
        logger.warning("%s: does not exist", str(config_path))
        return []

    try:
        cfg = Configuration(str(config_path))

        build_after = cfg.config().get("build_after")
    except Exception as exc:
        logger.exception(exc)
        return []

    if not build_after:
        return []

    return build_after
