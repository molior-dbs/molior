import asyncio
import click

from sqlalchemy.orm import sessionmaker
from launchy import Launchy
from async_cron.job import CronJob
from async_cron.schedule import Scheduler

from ..app import app, logger
from ..version import MOLIOR_VERSION
from ..model.database import database
from ..auth import Auth

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

loop = asyncio.get_event_loop()


async def cleanup_task():
    await enqueue_aptly({"cleanup": []})


async def main():
    # OBSOLETE schedule any missed builds
    # logger.info("source repository scan: starting")
    # await asyncio.ensure_future(startup_scan())
    # logger.info("source repository scan: finished")

    worker = Worker()
    asyncio.ensure_future(worker.run())

    backend_worker = BackendWorker()
    asyncio.ensure_future(backend_worker.run())

    aptly_worker = AptlyWorker()
    asyncio.ensure_future(aptly_worker.run())

    notification_worker = NotificationWorker()
    asyncio.ensure_future(notification_worker.run())

    cleanup_sched = Scheduler(locale="en_US")
    # cleanup_job = CronJob(name='cleanup').every().hour.at(":34").go(cleanup_task, (5), age=99)
    cleanup_job = CronJob(name='cleanup').every(5).hours.go(cleanup_task)
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
def mainloop(host, port, debug):
    """
    Starts the molior app.
    """
    app.set_context_functions(create_cirrina_context, destroy_cirrina_context)
    app.run(host, port, logger=logger, debug=debug)


if __name__ == "__main__":
    logger.info("molior v%s", MOLIOR_VERSION)

    Launchy.attach_loop(loop)

    backend = Backend().init()
    if not backend:
        exit(1)
    if not Auth().init():
        exit(1)
    asyncio.ensure_future(main())
    mainloop()
