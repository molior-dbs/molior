"""
Provides functions to write to a build logfile.
"""
import pytz
from datetime import datetime
from pathlib import Path

from .configuration import Configuration

BORDER = 80 * "+"


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
    local_tz = pytz.timezone("Europe/Zurich")
    now = local_tz.localize(datetime.now(), is_dst=None)
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
