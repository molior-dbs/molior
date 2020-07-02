import socket
import json
import aiohttp

from pathlib import Path
from enum import Enum

from molior.app import logger
from .emailer import send_mail
from .configuration import Configuration
from molior.molior.queues import notification_queue


class Subject(Enum):
    """Provides the molior subject types"""

    websocket = 1
    eventwatch = 2
    userrole = 3
    user = 4
    project = 5
    projectversion = 6
    build = 7
    buildlog = 8
    mirror = 9


class Event(Enum):
    """Provides the molior event types"""

    added = 1
    changed = 2
    removed = 3
    connected = 4
    done = 5


class Action(Enum):
    """Provides the molior action types"""

    add = 1
    change = 2
    remove = 3
    start = 4
    stop = 5


async def trigger_hook(method, url, skip_ssl, body=None):
    """
    Triggers a web hook.

    Args:
        method (str): The http method to be used. E.g. POST
        url (str): The url to send the request to.
        skip_ssl (bool): Set to True if ssl handshake should not be verified.
        body (str): The request body, only pass if method is POST
    """
    data = None
    headers = {"content-type": "application/json"}
    verify = not skip_ssl

    try:
        data = json.loads(body)
    except Exception as exc:
        logger.error("hook: error parsing json body: {}".format(exc))
        return

    connector = aiohttp.TCPConnector(verify_ssl=verify)

    if method.lower() == "post":
        async with aiohttp.ClientSession(connector=connector) as http:
            async with http.post(url, headers=headers, data=json.dumps(data)) as resp:
                if resp.status != 200:
                    logger.warning("trigger web hook '%s' to '%s' returned %d ", method, url, resp.status)

    elif method.lower() == "get":
        async with aiohttp.ClientSession() as http:
            async with http.get(url) as resp:
                if resp.status != 200:
                    logger.warning("trigger web hook '%s' to '%s' returned %d ", method, url, resp.status)


def send_mail_notification(build):
    """
    Sends a build finished notification
    to the given receiver.

    Args:
        build: Model of the finished build.
        reciever (str): The reciever's email address.
    """
    cfg = Configuration()
    email_cfg = cfg.email_notifications
    if not email_cfg or not email_cfg.get("enabled"):
        return

    buildout_path = Path(cfg.working_dir) / "buildout"
    log_file = buildout_path / str(build.id) / "build.log"
    if not log_file.exists():
        logger.warning(
            "not sending notification: buildlog file '%s' does not exist!",
            str(log_file),
        )
        return

    template_file = Path("/etc/molior/email.template")
    with template_file.open() as _file:
        template = "".join(_file.readlines())

    pkg_name = build.sourcename
    receiver = build.maintainer.email
    r_name = build.maintainer.fullname

    version = build.version
    arch = build.buildconfiguration.buildvariant.architecture.name
    distrelease_version = build.buildconfiguration.buildvariant.base_mirror.name
    distrelease = build.buildconfiguration.buildvariant.base_mirror.project.name
    hostname = cfg.hostname if cfg.hostname else socket.getfqdn()
    link = "http://{}/#!/build/{}".format(hostname, build.id)

    if build.buildstate == "build_failed":
        subject = "Build Failed: {pkg_name} {version} ({distrelease}-{arch})".format(
            pkg_name=pkg_name, version=version, distrelease=distrelease, arch=arch
        )
        message = "Unfortunately the build failed for:"
    elif build.buildstate == "successful":
        subject = "Released: {pkg_name} {version} ({distrelease}-{arch})".format(
            pkg_name=pkg_name, version=version, distrelease=distrelease, arch=arch
        )
        message = "I've just finished building the debian packages for:"
    else:
        logger.warning(
            "not sending notification: build has state '%s'", str(build.buildstate)
        )
        return

    content = template.format(
        receiver_name=r_name,
        message=message,
        package_name=pkg_name,
        build_version=version,
        distrelease=distrelease,
        distrelease_version=distrelease_version,
        arch=arch,
        build_log_link=link,
    )
    send_mail(receiver, subject, content, [str(log_file)])


async def notify(subject, event, data):
    await notification_queue.put({"notify": {"subject": subject, "event": event, "data": data}})


async def run_hooks(build_id):
        await notification_queue.put({"hooks": {"build_id": build_id}})
