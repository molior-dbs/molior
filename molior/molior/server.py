import asyncio
import click
import signal
import functools

from sqlalchemy.orm import sessionmaker
from launchy import Launchy
from async_cron.job import CronJob
from async_cron.schedule import Scheduler

from ..app import app, logger
from ..version import MOLIOR_VERSION
from ..model.database import database
from ..auth import Auth
from .configuration import Configuration

from .worker import Worker
from .worker_aptly import AptlyWorker
from .worker_backend import BackendWorker
from .worker_notification import NotificationWorker
from .backend import Backend
from .queues import enqueue_aptly

# import api handlers
import molior.api.build              # noqa: F401
import molior.api.gitlab             # noqa: F401
import molior.api.bitbucket          # noqa: F401
import molior.api.project            # noqa: F401
import molior.api.buildstate         # noqa: F401
import molior.api.mirror             # noqa: F401
import molior.api.websocket          # noqa: F401
import molior.api.auth               # noqa: F401
import molior.api.user               # noqa: F401
import molior.api.userrole           # noqa: F401
import molior.api.sourcerepository   # noqa: F401
import molior.api.projectuserrole    # noqa: F401
import molior.api.projectversion     # noqa: F401
import molior.api.info               # noqa: F401
import molior.api.status             # noqa: F401
import molior.api.hook               # noqa: F401
import molior.api.upload             # noqa: F401

import molior.api2.project           # noqa: F401
import molior.api2.projectversion    # noqa: F401
import molior.api2.sourcerepository  # noqa: F401
import molior.api2.user              # noqa: F401
import molior.api2.mirror            # noqa: F401
import molior.api2.build             # noqa: F401
import molior.api2.token             # noqa: F401


class MoliorServer:

    def __init__(self, loop, host, port, logger, debug):
        self.loop = loop
        self.host = host
        self.port = port
        self.logger = logger
        self.debug = debug
        self.task_worker = None
        self.task_backend_worker = None
        self.task_aptly_worker = None
        self.task_notification_worker = None
        self.task_cron = None

    @staticmethod
    def create_cirrina_context(cirrina):
        maker = sessionmaker(bind=database.engine)
        cirrina.add_context("db_session", maker())

    @staticmethod
    def destroy_cirrina_context(cirrina):
        cirrina.db_session.close()

    async def cleanup_task(self):
        await enqueue_aptly({"cleanup": []})

    def run(self):
        self.backend = Backend().init()
        if not self.backend:
            return
        if not Auth().init():
            return

        Launchy.attach_loop(self.loop)

        worker = Worker()
        self.task_worker = asyncio.ensure_future(worker.run())

        backend_worker = BackendWorker()
        self.task_backend_worker = asyncio.ensure_future(backend_worker.run())

        aptly_worker = AptlyWorker()
        self.task_aptly_worker = asyncio.ensure_future(aptly_worker.run())

        notification_worker = NotificationWorker()
        self.task_notification_worker = asyncio.ensure_future(notification_worker.run())

        cfg = Configuration()
        daily_cleanup = cfg.aptly.get("daily_cleanup")
        if daily_cleanup is False or daily_cleanup == "off" or daily_cleanup == "disabled":
            return

        if not daily_cleanup:
            daily_cleanup = "04:00"
        cleanup_sched = Scheduler(locale="en_US")
        cleanup_job = CronJob(name='cleanup').every().day.at(daily_cleanup).go(self.cleanup_task)
        cleanup_sched.add_job(cleanup_job)
        self.task_cron = asyncio.ensure_future(cleanup_sched.start())

        app.set_context_functions(MoliorServer.create_cirrina_context, MoliorServer.destroy_cirrina_context)
        app.run(self.host, self.port, logger=self.logger, debug=self.debug)

    async def terminate(self):

        logger.info("terminating tasks")

        self.task_worker.cancel()
        self.task_backend_worker.cancel()
        self.task_aptly_worker.cancel()
        self.task_notification_worker.cancel()

        try:
            await self.task_worker
            await self.task_backend_worker
            await self.task_aptly_worker
            await self.task_notification_worker
        except asyncio.CancelledError:
            logger.info("tasks were canceled")
        else:
            logger.info("tasks were completed")

        try:
            logger.info("terminating backend")
            await self.backend.stop()
        except asyncio.CancelledError:
            logger.info("backend tasks were completed")

        try:
            logger.info("terminating launchy")
            await Launchy.stop()
        except asyncio.CancelledError:
            logger.info("launchy tasks were completed")

        logger.info("terminating app")
        app.stop()


@click.command()
@click.option("--host",     default="localhost",         help="Hostname, examples: 'localhost' or '0.0.0.0'")
@click.option("--port",     default=8888,                help="Listen port")
@click.option("--debug",    default=False, is_flag=True, help="Enable debug")
@click.option("--coverage", default=False, is_flag=True, help="Enable coverage testing")
def main(host, port, debug, coverage):
    logger.info("starting molior v%s", MOLIOR_VERSION)

    if coverage:
        logger.warning("starting coverage measurement")
        import coverage
        cov = coverage.Coverage(source=["molior"])
        cov.start()

    loop = asyncio.get_event_loop()
    moliorserver = MoliorServer(loop, host, port, logger=logger, debug=debug)

    def terminate(signame):
        logger.info("received %s, terminating...", signame)
        asyncio.run_coroutine_threadsafe(moliorserver.terminate(), loop)
        # tasks = [task for task in asyncio.all_tasks() if task is not asyncio.tasks.current_task()]
        # list(map(lambda task: task.cancel(), tasks))
        # await asyncio.gather(*tasks, return_exceptions=True)
        # try:
        #     loop.stop()
        # except Exception as exc:
        #     logger.exception(exc)
        # logger.info("event loop stopped")

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame), functools.partial(terminate, signame))

    moliorserver.run()  # server up and running ...

    if coverage:
        logger.warning("saving coverage measurement")
        cov.stop()
        cov.html_report(directory='/var/lib/molior/buildout/coverage')

    logger.info("terminated")


if __name__ == "__main__":
    main()
