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


async def cleanup_task():
    await enqueue_aptly({"cleanup": []})


async def main():
    worker = Worker()
    asyncio.ensure_future(worker.run())

    backend_worker = BackendWorker()
    asyncio.ensure_future(backend_worker.run())

    aptly_worker = AptlyWorker()
    asyncio.ensure_future(aptly_worker.run())

    notification_worker = NotificationWorker()
    asyncio.ensure_future(notification_worker.run())

    cfg = Configuration()
    daily_cleanup = cfg.aptly.get("daily_cleanup")
    if not daily_cleanup:
        daily_cleanup = "04:00"
    cleanup_sched = Scheduler(locale="en_US")
    cleanup_job = CronJob(name='cleanup').every().day.at(daily_cleanup).go(cleanup_task)
    cleanup_sched.add_job(cleanup_job)
    asyncio.ensure_future(cleanup_sched.start())


def create_cirrina_context(cirrina):
    maker = sessionmaker(bind=database.engine)
    cirrina.add_context("db_session", maker())


def destroy_cirrina_context(cirrina):
    cirrina.db_session.close()


@click.command()
@click.option(
    "--host", default="localhost", help="Hostname, examples: 'localhost' or '0.0.0.0'"
)
@click.option("--port", default=8888, help="Listen port")
@click.option("--debug", default=False, help="Enable debug")
@click.option("--coverage", default=False, help="Enable coverage testing")
def mainloop(host, port, debug, coverage):
    logger.info("molior v%s", MOLIOR_VERSION)

    if coverage:
        logger.warning("starting coverage measurement")
        import coverage
        cov = coverage.Coverage(source=["molior"])
        cov.start()

    loop = asyncio.get_event_loop()
    Launchy.attach_loop(loop)

    def terminate(signame):
        logger.info("terminating")
        asyncio.run_coroutine_threadsafe(Launchy.stop(), loop)
        try:
            loop.stop()
        except Exception:
            pass
        logger.info("event loop stopped")

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame), functools.partial(terminate, signame))

    backend = Backend().init()
    if not backend:
        exit(1)
    if not Auth().init():
        exit(1)

    asyncio.ensure_future(main())
    app.set_context_functions(create_cirrina_context, destroy_cirrina_context)
    app.run(host, port, logger=logger, debug=debug)
    logger.info("terminated")

    if coverage:
        logger.warning("saving coverage measurement")
        cov.stop()
        cov.html_report(directory='/var/lib/molior/buildout/coverage')


if __name__ == "__main__":
    mainloop()
