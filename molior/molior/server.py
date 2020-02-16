"""
Provides the main molior server.
"""
import asyncio
import concurrent.futures
import click

from sqlalchemy.orm import sessionmaker
from launchy import Launchy
from async_cron.job import CronJob
from async_cron.schedule import Scheduler

from molior.app import logger
from molior.molior.worker import Worker
from molior.molior.worker_aptly import AptlyWorker
from molior.molior.worker_backend import BackendWorker, backend_queue
from molior.molior.worker_notification import NotificationWorker
from molior.model.database import database
from molior.app import app
from molior.version import MOLIOR_VERSION

from molior.molior.backend import Backend
from molior.auth import Auth

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
import molior.api.architecture       # noqa: F401
import molior.api.sourcerepository   # noqa: F401
import molior.api.projectuserrole    # noqa: F401
import molior.api.projectversion     # noqa: F401
import molior.api.info               # noqa: F401
import molior.api.buildvariant       # noqa: F401
import molior.api.status             # noqa: F401
import molior.api.hook               # noqa: F401
import molior.api.upload             # noqa: F401

import molior.api2.project           # noqa: F401
import molior.api2.projectversion    # noqa: F401
import molior.api2.sourcerepository  # noqa: F401
import molior.api2.user              # noqa: F401

processed_repos = []

loop = asyncio.get_event_loop()

# worker queues
task_queue = asyncio.Queue()
aptly_queue = asyncio.Queue()


def run_backend_thread(backend):
    """
    Starts the threads
    """
    import threading

    backend_thread = threading.Thread(target=backend.run)
    backend_thread.start()
    logger.info("joining backend thread")
    backend_thread.join()
    logger.info("backend thread terminated")


async def cleanup_task(aptly_queue):
    await aptly_queue.put({"cleanup": []})


async def main(backend):
    # OBSOLETE schedule any missed builds
    # logger.info("source repository scan: starting")
    # await asyncio.ensure_future(startup_scan())
    # logger.info("source repository scan: finished")

    worker = Worker(task_queue, aptly_queue)
    asyncio.ensure_future(worker.run())

    backend_worker = BackendWorker(task_queue, aptly_queue)
    asyncio.ensure_future(backend_worker.run())

    aptly_worker = AptlyWorker(aptly_queue, task_queue)
    asyncio.ensure_future(aptly_worker.run())

    notification_worker = NotificationWorker()
    asyncio.ensure_future(notification_worker.run())

    if hasattr(backend, "run"):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_backend_thread, backend)
        logger.info("asyncio threads terminated")

    # FIXME: await futures ?

    cleanup_sched = Scheduler(locale="en_US")
    # cleanup_job = CronJob(name='cleanup').every().hour.at(":34").go(cleanup_task, (5), age=99)
    cleanup_job = CronJob(name='cleanup').every(5).hours.go(cleanup_task, aptly_queue=aptly_queue)
    cleanup_sched.add_job(cleanup_job)
    asyncio.ensure_future(cleanup_sched.start())


def create_cirrina_context(cirrina):
    maker = sessionmaker(bind=database.engine)
    cirrina.add_context("db_session", maker())
    cirrina.add_context("task_queue", task_queue)
    cirrina.add_context("aptly_queue", aptly_queue)


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

    backend = Backend().init(backend_queue)
    if not backend:
        exit(1)
    if not Auth().init():
        exit(1)
    asyncio.ensure_future(main(backend))
    mainloop()  # pylint: disable=no-value-for-parameter
