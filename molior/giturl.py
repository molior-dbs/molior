"""
Git URL parsing (replaces the giturlparse package, which is not in Debian).

molior needs three parts of a git URL: the host (resource), the owner (the path between host and repo name,
may contain slashes or be None) and the repo name (last path element, without .git). The name becomes the
source repository name and its directory, so it must stay the same for the URLs molior already knows:
giturlparse returned the same name for all the forms below.

    https://host/owner/name.git, https://user:pass@host:8080/group/sub/name, ssh://git@host:7999/owner/name.git,
    git://host/owner/name.git, git@host:owner/name.git, host:owner/name.git
"""
import re

from collections import namedtuple

GitUrl = namedtuple("GitUrl", ["resource", "owner", "name"])


class GitUrlError(ValueError):
    """The string is not a git URL molior can use."""


# scheme://[user@]host[:port]/[owner/]name[.git][/]
_URL = re.compile(r"^(?:git\+)?[a-z][a-z0-9+.-]*://(?:[^@/]+@)?(?P<resource>[^/:@]+)(?::\d+)?"
                  r"/(?:(?P<owner>[^/]+(?:/[^/]+)*)/)?(?P<name>[^/]+?)(?:\.git)?/?$", re.IGNORECASE)
# [user@]host:[owner/]name[.git][/]   (scp-like syntax of git and ssh)
_SCP = re.compile(r"^(?:[^@/:]+@)?(?P<resource>[^/:@]+):(?!/)(?:(?P<owner>[^/]+(?:/[^/]+)*)/)?"
                  r"(?P<name>[^/]+?)(?:\.git)?/?$")


def parse_git_url(url):
    """
    Returns GitUrl(resource, owner, name) of a git URL, raises GitUrlError if the URL has no host or no
    repo name.
    """
    for regex in (_URL, _SCP):
        match = regex.match(url or "")
        if match and match.group("name"):
            return GitUrl(match.group("resource"), match.group("owner"), match.group("name"))
    raise GitUrlError("Invalid git URL '{}'".format(url))
