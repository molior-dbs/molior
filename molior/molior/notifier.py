"""
Provides functions to send notifications to molior-web clients
"""
import socket
from pathlib import Path
import aiohttp

import json
from jinja2 import Template

from molior.api.messagetypes import Subject, Event
from .emailer import send_mail
from .configuration import Configuration
from .worker_notification import notification_queue

from .logger import get_logger

logger = get_logger()


def _get_build_data(build):
    """
    Returns the given build model
    as formatted dict.

    Args:
        build (molior.model.build.Build): The build model.

    Returns:
        dict: The data dict.
    """
    maintainer = "-"
    if build.maintainer:
        maintainer = "{} {}".format(
            build.maintainer.firstname, build.maintainer.surname
        )

    data = {
        "id": build.id,
        "startstamp": str(build.startstamp),
        "endstamp": str(build.endstamp),
        "buildstate": build.buildstate,
        "buildtype": build.buildtype,
        "branch": build.ci_branch,
        "git_ref": build.git_ref,
        "sourcename": build.sourcename,
        "version": build.version,
        "maintainer": maintainer,
    }
    if build.sourcerepository:
        data.update(
            {
                "sourcerepository": {
                    "id": build.sourcerepository.id,
                    "url": build.sourcerepository.url,
                    "name": build.sourcerepository.name,
                }
            }
        )
    if build.buildconfiguration:
        data.update(
            {
                "buildvariant": {
                    "architecture": {
                        "id": build.buildconfiguration.buildvariant.architecture.id,
                        "name": build.buildconfiguration.buildvariant.architecture.name,
                    },
                    "basemirror": {
                        "id": build.buildconfiguration.buildvariant.base_mirror.id,
                        "version": build.buildconfiguration.buildvariant.base_mirror.name,
                        "name": build.buildconfiguration.buildvariant.base_mirror.project.name,
                    },
                    "name": build.buildconfiguration.buildvariant.name,
                },
                "projectversion_id": build.buildconfiguration.projectversions[0].id,
            }
        )
    return data


async def build_added(build):
    """
    Sends a `build_added` notification to the web clients

    Args:
        build (molior.model.build.Build): The build model.
    """
    logger.debug(
        "notifying web clients that build with id '%s' was added with state '%s'",
        build.id,
        build.buildstate,
    )
    data = _get_build_data(build)
    args = {
        "notify": {
            "event": Event.added.value,
            "subject": Subject.build.value,
            "data": data,
        }
    }
    await notification_queue.put(args)


async def build_changed(build):
    """
    Sends a `build_changed` notification to the web clients

    Args:
        build (molior.model.build.Build): The build model.
    """
    logger.debug(
        "notifying web client that build with id '%s' was changed to '%s'",
        build.id,
        build.buildstate,
    )
    data = _get_build_data(build)
    args = {
        "notify": {
            "event": Event.changed.value,
            "subject": Subject.build.value,
            "data": data,
        }
    }
    await notification_queue.put(args)

    # only run hooks for deb builds
    if build.buildtype != "deb":
        return

    # only send building, ok, nok
    if (
        build.buildstate != "building"
        and build.buildstate != "successful"
        and build.buildstate != "build_failed"
        and build.buildstate != "publish_failed"
    ):
        return

    maintainer = build.maintainer

    cfg_host = Configuration().hostname
    hostname = cfg_host if cfg_host else socket.getfqdn()

    class ResultObject:
        pass

    repository = ResultObject()
    if build.sourcerepository:
        repository.url = build.sourcerepository.url
        repository.name = build.sourcerepository.name

    buildres = ResultObject()
    buildres.id = build.id
    buildres.status = build.buildstate
    buildres.version = build.version
    buildres.url = "http://{}/build/{}".format(hostname, build.id)
    buildres.raw_log_url = "http://{}/buildout/{}/build.log".format(hostname, build.id)
    buildres.commit = build.git_ref
    buildres.branch = build.ci_branch

    platform = ResultObject()
    if build.buildconfiguration:
        platform.distrelease = (
            build.buildconfiguration.buildvariant.base_mirror.project.name
        )
        platform.version = build.buildconfiguration.buildvariant.base_mirror.name
        platform.architecture = build.buildconfiguration.buildvariant.architecture.name

    project = ResultObject()
    if build.buildconfiguration:
        project.name = build.buildconfiguration.projectversions[0].project.name
        project.version = build.buildconfiguration.projectversions[0].name

    args = {
        "repository": repository,
        "build": buildres,
        "platform": platform,
        "maintainer": maintainer,
        "project": project,
    }

    if build.sourcerepository:
        for hook in build.sourcerepository.hooks:
            if not hook.enabled:
                continue

            try:
                url = Template(hook.url).render(**args)
                body = Template(hook.body).render(**args)

                await trigger_hook(hook.method, url, skip_ssl=hook.skip_ssl, body=body)
            except Exception as exc:
                logger.error(
                    "could not trigger web hook '%s' to '%s': %s", hook.method, url, exc
                )


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
        logger.error("could not trigger web hook '%s' to '%s': %s", method, url, exc)
        return

    connector = aiohttp.TCPConnector(verify_ssl=verify)

    if method.lower() == "post":
        async with aiohttp.ClientSession(connector=connector) as http:
            async with http.post(url, headers=headers, data=json.dumps(data)) as resp:
                if resp.status != 200:
                    logger.warning(
                        "trigger web hook '%s' to '%s' returned %d ",
                        method,
                        url,
                        resp.status,
                    )

    elif method.lower() == "get":
        async with aiohttp.ClientSession() as http:
            async with http.get(url) as resp:
                if resp.status != 200:
                    logger.warning(
                        "trigger web hook '%s' to '%s' returned %d ",
                        method,
                        url,
                        resp.status,
                    )


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
