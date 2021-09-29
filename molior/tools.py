import re
import pytz
import json

from datetime import datetime
from pathlib import Path
from launchy import Launchy
from aiohttp.web import json_response
from aiofile import AIOFile, Writer

from .app import logger
from .molior.configuration import Configuration

local_tz = None


def OKResponse(msg="", status=200):
    return json_response(status=status, text=json.dumps(msg))


def ErrorResponse(status, msg):
    logger.info("API Error: %s", msg)
    return json_response(status=status, text=json.dumps(msg))


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

    version_pattern = "^v[0-9]"
    pattern = re.compile(version_pattern)
    return pattern.match(version) is not None


def is_name_valid(name):
    """
    Returns whether a version/project name is valid or not

    Args:
        name (str): The name of the version
    """
    return bool(re.compile(r"^[a-zA-Z0-9.-]+$").match(name))


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

    process = Launchy("dpkg-parsechangelog -S {}".format(name), outh, errh, cwd=str(path))
    await process.launch()
    ret = await process.wait()
    if ret != 0:
        logger.error("error occured while getting changelog attribute: %s", err)
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


async def write_log(build_id, line):
    """
    Writes given line to logfile for given
    build_id.

    Args:
        build_id (int): The build's id.
        line (string): The log line.

    """
    path = Path(Configuration().working_dir) / "buildout" / str(build_id) / "build.log"
    if not path.parent.exists():
        path.parent.mkdir()

    async with AIOFile(path, "a+") as afp:
        writer = Writer(afp)
        await writer(line)


async def write_log_title(build_id, line, no_footer_newline=False, no_header_newline=True, error=False):
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

    BORDER = 80 * "+"

    path = Path(Configuration().working_dir) / "buildout" / str(build_id) / "build.log"
    if not path.parent.exists():
        path.parent.mkdir()
    async with AIOFile(path, "a+") as afp:
        writer = Writer(afp)
        await writer("{}\x1b[{}m\x1b[1m{}\x1b[0m\n".format(header_newline, color, BORDER))
        await writer("\x1b[{}m\x1b[1m| molior: {:36} {} |\x1b[0m\n".format(color, line, date))
        await writer("\x1b[{}m\x1b[1m{}\x1b[0m\n{}".format(color, BORDER, footer_newline))


def array2db(array):
    return "{{{}}}".format(",".join(array))


def db2array(val):
    if not val:
        return []
    return val[1:-1].split(",")


def escape_for_like(query: str) -> str:
    """Escape query string for use in (I)LIKE database queries."""
    # Escape characters that have a special meaning in "like" queries
    return query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
