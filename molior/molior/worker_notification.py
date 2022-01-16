import socket

from jinja2 import Template

from ..app import app, logger
from ..model.database import Session
from ..model.build import Build
from ..model.sourepprover import SouRepProVer
from ..model.postbuildhook import PostBuildHook
from ..model.hook import Hook

from .notifier import trigger_hook
from .configuration import Configuration
from .queues import dequeue_notification


class NotificationWorker:
    """
    Notification task

    """

    async def run(self):
        """
        Run the worker task.
        """

        while True:
            handled = False
            try:
                task = await dequeue_notification()
                if task is None:
                    break

                notification = task.get("notify")
                if notification:
                    await app.websocket_broadcast(notification)
                    handled = True

                notification = task.get("hooks")
                if notification:
                    await self.do_hooks(notification.get("build_id"))
                    handled = True

                if not handled:
                    logger.error("notification: got unknown task %s", str(task))

            except Exception as exc:
                logger.exception(exc)

        logger.info("notification task terminated")

    async def do_hooks(self, build_id):
        hooks = []
        with Session() as session:
            build = session.query(Build).filter(Build.id == build_id).first()
            if not build:
                logger.error("hooks: build {} not found".format(build_id))
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
            if build.projectversion.basemirror:
                platform.distrelease = build.projectversion.basemirror.project.name
                platform.version = build.projectversion.basemirror.name
                platform.architecture = build.architecture

            project = ResultObject()
            if build.projectversion:
                project.name = build.projectversion.project.name
                project.version = build.projectversion.name

            args = {
                "repository": repository,
                "build": buildres,
                "platform": platform,
                "maintainer": maintainer,
                "project": project,
            }

            if not build.sourcerepository or not build.projectversion:
                logger.warning("hook: no source repo and no projectversion")
                return

            buildconfig = session.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == build.sourcerepository_id,
                                                             SouRepProVer.projectversion_id == build.projectversion_id).first()
            if not buildconfig:
                logger.warning("hook: source repo not in projectversion")
                return
            postbuildhooks = session.query(Hook).join(PostBuildHook).filter(
                    PostBuildHook.sourcerepositoryprojectversion_id == buildconfig.id)
            for hook in postbuildhooks:
                method = None
                url = None
                skip_ssl = None
                body = None

                if not hook.enabled:
                    logger.warning("hook: not enabled")
                    continue

                if build.buildtype == "build" and not hook.notify_overall:
                    logger.info("hook: top build not enabled")
                    continue

                if build.buildtype == "source" and not hook.notify_src:
                    logger.info("hook: src build not enabled")
                    continue

                if build.buildtype == "deb" and not hook.notify_deb:
                    logger.info("hook: deb build not enabled")
                    continue

                try:
                    url = Template(hook.url).render(**args)
                except Exception as exc:
                    logger.error("hook: error rendering URL template", url, exc)
                    continue

                if hook.body:
                    try:
                        body = Template(hook.body).render(**args)
                    except Exception as exc:
                        logger.error("hook: error rendering BODY template", url, exc)
                        continue

                method = hook.method
                skip_ssl = hook.skip_ssl

                logger.info("adding hook: %s" % url)
                hooks.append((method, url, skip_ssl, body))

        for hook in hooks:
            try:
                await trigger_hook(hook[0], hook[1], skip_ssl=hook[2], body=hook[3])
            except Exception as exc:
                logger.error("hook: error calling {} '{}': {}".format(hook[0], hook[1], exc))
