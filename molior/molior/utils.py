"""
Provides utilities for molior core.
"""
import re
import os
import shlex
from launchy import Launchy

from molior.aptly import AptlyApi
from .configuration import Configuration
from .logger import get_logger

logger = get_logger()


def get_aptly_connection():
    """
    Connects to aptly server and returns aptly
    object.

    Returns:
        AptlyApi: The connected aptly api instance.
    """
    cfg = Configuration()
    api_url = cfg.aptly.get("api_url")
    gpg_key = cfg.aptly.get("gpg_key")
    aptly_user = cfg.aptly.get("user")
    aptly_passwd = cfg.aptly.get("pass")
    aptly = AptlyApi(api_url, gpg_key, username=aptly_user, password=aptly_passwd)
    return aptly


def parse_repository_name(url):
    """
    Returns the repository name
    of a git clone url.

    Args:
        url (str): Git clone url to parse

    Returns:
        name (str): The name of the repository

    Examples:
        >>> url = 'ssh://git@foo.com:1337/~jon/foobar.git'
        >>> parse_repository_name(repo_name)
        >>> 'foobar'
        or:
        >>> url = 'ssh://git@foo.com:1337/~jon/foobar'
        >>> parse_repository_name(repo_name)
        >>> 'foobar'
    """
    if url.endswith(".git"):
        search = re.search(r"([0-9a-zA-Z_\-.]+).git$", url)
        if search:
            return search.group(1)
    return os.path.basename(url)


async def get_changelog_attr(name, path):
    """
    Gets given changelog attribute from given
    repository path.

    Args:
        name (str): The attr's name.
        path (pathlib.Path): The repo's path.
    """
    attr = ""
    err = ""

    async def outh(line):
        nonlocal attr
        attr += line

    async def errh(line):
        nonlocal err
        err += line

    process = Launchy(shlex.split("dpkg-parsechangelog -S {}".format(name)), outh, errh, cwd=str(path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        logger.error("error occured while getting changelog attribute: %s", str(err, "utf-8"))
        raise Exception("error running dpkg-parsechangelog")

    return attr.strip()
