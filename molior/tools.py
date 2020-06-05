import re
import shlex
import pytz

from datetime import datetime
from pathlib import Path
from launchy import Launchy
from aiohttp.web import Response

from .app import logger
from .aptly import AptlyApi
from .molior.configuration import Configuration

from .model.projectversion import ProjectVersion
from .model.project import Project
from .model.buildvariant import BuildVariant
from .model.architecture import Architecture
from .model.user import User
from .model.userrole import UserRole

BORDER = 80 * "+"
local_tz = None


def ErrorResponse(status, msg):
    logger.info("API Error: %s", msg)
    return Response(status=status, text=msg)


def paginate(request, query):
    page = request.GET.getone("page", None)
    page_size = request.GET.getone("page_size", None)

    if not page:
        return query

    if not page_size:
        page_size = request.GET.getone("per_page", None)
        if not page_size:
            return query

    try:
        page = int(page)
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1

    try:
        page_size = int(page_size)
        if page_size < 1:
            page_size = 10
    except (ValueError, TypeError):
        page_size = 10

    return query.limit(page_size).offset((page - 1) * page_size)


def check_admin(web_session, db_session):
    """
    Helper to check current user is admin
    """
    if "username" in web_session:
        res = db_session.query(User).filter_by(username=web_session["username"]).first()
        if not res:
            return False
        return res.is_admin
    return False


def parse_int(value):
    """
    Parses the given value and returns
    it as an integer.

    Args:
        value (str): The string to be parsed.
    Returns:
        int: The parsed value or None
    """
    if not value:
        return None
    try:
        parsed_val = int(value)
    except ValueError:
        return None
    return parsed_val


def check_user_role(web_session, db_session, project_id, role, allow_admin=True):
    """
    Helper to enforce the current user as a certain role for a given project

    Input :
        * session <multiDict>
        * project_id <int>
        * role <str> or [<str>,<str>,...] : one or multiple role or "any"
        * allow_admin <bool> : allow admin to bypass

    Output : return a boolean
        * True : the use

    Examples :

        if( not check_user_role( ThisProject, ThisRole)):
            return web.Response(status=401, text="permission denied")

        if( not check_user_role( ThisProject, "any")):
            return web.Response(status=401,
                                text="You need a role on the project")

        if( not check_user_role( ThisProject, "owner")):
            return web.Response(status=401,
                                text="Only project owner can do this")

    """
    project_id = parse_int(project_id)
    if not project_id:
        return False

    if "username" not in web_session:
        return False  # no session

    user = (
        db_session.query(User)
        .filter_by(username=web_session["username"])  # pylint: disable=no-member
        .first()
    )
    if not user:
        return False

    if allow_admin and user.is_admin:
        return True

    project = db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return False

    logger.debug("searching role for user %d and project %d", user.id, project.id)
    role_rec = db_session.query(UserRole).filter_by(user=user, project=project).first()
    if not role_rec:
        return False

    roles = [role] if isinstance(role, str) else role

    if "any" in roles or role_rec.role in roles:
        return True

    return False


def get_buildvariants(session, basemirror_name, basemirror_version, architectures):
    """
    Gets all buildvariants matching a specific basemirror and architectures

    Args:
        basemirror_name (str): Name of the basemirror (e.g. 'stretch', 'jessie')
        basemirror_version (str): Version of the basemirror (e.g. '9.6', '8.10')
        architectures (list): Architectures (e.g. ["amd64", "armhf"])
    """
    return (
        session.query(BuildVariant)
        .join(Architecture)
        .join(ProjectVersion)
        .join(Project)
        .filter(Project.name == basemirror_name)
        .filter(ProjectVersion.name == basemirror_version)
        .filter(Architecture.name.in_(architectures))
        .all()
    )


def get_hook_triggers(hook):
    triggers = []
    if hook.notify_src:
        triggers.append("src")
    if hook.notify_deb:
        triggers.append("deb")
    if hook.notify_overall:
        triggers.append("overall")
    return triggers


def validate_version_format(version: str):
    """
    Returns True if a version name is in the valid format (see below). False otherwise

    versions may have
     - have an optional leading 'v'
     - 1-4 dot-separated multi-digits (the only mandatory part)
     - optional trailing alphanumeric words, separated by '~', '+' or '-'

    valid examples: '1.0.0', 'v1.0.0', 'v1.2.33~alpha123'

    Args:
        version (str): the version string to check
    """

    version_pattern = "^v?[0-9]([0-9a-zA-Z]*\\.?[0-9a-zA-Z]+)*([~+-]*[0-9a-zA-Z\\.]*[0-9a-zA-Z]+)?$"
    pattern = re.compile(version_pattern)
    return pattern.match(version) is not None


def is_name_valid(name):
    """
    Returns whether a version/project name is valid or not

    Args:
        name (str): The name of the version
    """
    return bool(re.compile(r"^[a-zA-Z0-9.-]+$").match(name))


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


def strip_epoch_version(version):
    m = re.match(r"(?:\d+:)?(\d.+)", version)
    if m:
        version = m.groups()[0]
    return version


def get_local_tz():
    global local_tz
    if local_tz:
        return local_tz

    timezone = "Europe/Zurich"
    f = open("/etc/timezone", "r")
    if f:
        timezone = f.read().strip()
        f.close()
    local_tz = pytz.timezone(timezone)
    return local_tz


def write_log(build_id, line):
    """
    Writes given line to logfile for given
    build_id.

    Args:
        build_id (int): The build's id.
        lines (list): The log line.

    Returns:
        bool: True if successful, otherwise False.
    """
    path = Path(Configuration().working_dir) / "buildout" / str(build_id) / "build.log"
    if not path.parent.exists():
        path.parent.mkdir()

    with path.open(mode="a+", encoding="utf-8") as log_file:
        log_file.write(line)

    return True


def write_log_title(build_id, line, no_footer_newline=False, no_header_newline=True, error=False):
    """
    Writes given line as title to logfile for
    given build_id.

    Args:
        build_id (int): The build's id.
        lines (list): The log line.
    """
    now = get_local_tz().localize(datetime.now(), is_dst=None)
    date = datetime.strftime(now, "%a, %d %b %Y %H:%M:%S %z")

    header_newline = "\n"
    if no_header_newline:
        header_newline = ""

    footer_newline = "\n"
    if no_footer_newline:
        footer_newline = ""

    color = 36
    if error:
        color = 31

    write_log(build_id, "{}\x1b[{}m\x1b[1m{}\x1b[0m\n".format(header_newline, color, BORDER))
    write_log(build_id, "\x1b[{}m\x1b[1m| molior: {:36} {} |\x1b[0m\n".format(color, line, date))
    write_log(build_id, "\x1b[{}m\x1b[1m{}\x1b[0m\n{}".format(color, BORDER, footer_newline))
