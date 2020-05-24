import socket

from jinja2 import Template

from molior.app import app, logger
from molior.molior.notifier import trigger_hook
from molior.molior.configuration import Configuration
from molior.model.database import Session
from molior.model.build import Build
from molior.molior.queues import notification_queue


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
                task = await notification_queue.get()
                if task is None:
                    logger.info("notification:: got emtpy task, aborting...")
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

                notification_queue.task_done()

            except Exception as exc:
                logger.exception(exc)

        logger.info("terminating notification task")

    async def do_hooks(self, build_id):
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
            if build.buildconfiguration:
                platform.distrelease = build.buildconfiguration.buildvariant.base_mirror.project.name
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
                    except Exception as exc:
                        logger.error("hook: error rendering URL template", url, exc)
                        return

                    try:
                        body = Template(hook.body).render(**args)
                    except Exception as exc:
                        logger.error("hook: error rendering BODY template", url, exc)
                        return

                    try:
                        await trigger_hook(hook.method, url, skip_ssl=hook.skip_ssl, body=body)
                    except Exception as exc:
                        logger.error("hook: error calling {} '{}': {}".format(hook.method, url, exc))
