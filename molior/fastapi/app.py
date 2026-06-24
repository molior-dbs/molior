"""
FastAPI application factory.

Mirrors the role of molior/app.py but wires up FastAPI instead of cirrina.
Startup/shutdown lifecycle (workers, backend, cron) is unchanged — only the
HTTP layer is replaced.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..logger import logger
from ..version import MOLIOR_VERSION
from ..molior.backend import Backend
from ..auth.auth import Auth
from ..molior.worker import Worker
from ..molior.worker_aptly import AptlyWorker
from ..molior.worker_backend import BackendWorker
from ..molior.worker_notification import NotificationWorker
from ..molior.queues import enqueue_aptly
import asyncio
from async_cron.job import CronJob
from async_cron.schedule import Scheduler
from contextlib import suppress
from launchy import Launchy
from ..model.metadata import MetaData
from ..model.database import Session


def get_weekday_number(weekday_name):
    return {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6,
    }.get(weekday_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start workers on startup, cancel them on shutdown — identical logic to MoliorServer.run_molior."""
    logger.info("starting molior v%s (fastapi)", MOLIOR_VERSION)

    app.state.backend = Backend().init()
    if not app.state.backend:
        raise RuntimeError("Backend init failed")
    if not Auth().init():
        raise RuntimeError("Auth init failed")

    Launchy.attach_loop(asyncio.get_event_loop())

    worker = Worker()
    aptly_worker = AptlyWorker()
    backend_worker = BackendWorker()
    notification_worker = NotificationWorker()

    task_worker = asyncio.ensure_future(worker.run())
    task_aptly = asyncio.ensure_future(aptly_worker.run())
    task_backend = asyncio.ensure_future(backend_worker.run())
    task_notification = asyncio.ensure_future(notification_worker.run(app))

    task_cron = None
    with Session() as session:
        cleanup_active = session.query(MetaData).filter_by(name="cleanup_active").first()
        cleanup_weekdays = session.query(MetaData).filter_by(name="cleanup_weekdays").first()
        cleanup_time = session.query(MetaData).filter_by(name="cleanup_time").first()

        if cleanup_active and cleanup_weekdays and cleanup_time:
            if cleanup_active.value.lower() != "false":
                sched = Scheduler(locale="en_US")
                for weekday in cleanup_weekdays.value.split(","):
                    logger.info("cleanup job: every %s at %s", weekday, cleanup_time.value)
                    job = CronJob(name=f"cleanup_{weekday}")
                    job.every().weekday(get_weekday_number(weekday)).at(cleanup_time.value).go(
                        lambda: asyncio.ensure_future(enqueue_aptly({"cleanup": []}))
                    )
                    sched.add_job(job)
                task_cron = asyncio.ensure_future(sched.start())

    yield  # ---- application runs here ----

    logger.info("shutting down molior")
    for task in [task_worker, task_aptly, task_backend, task_notification]:
        task.cancel()
    if task_cron:
        task_cron.cancel()

    for task in [task_worker, task_aptly, task_backend, task_notification]:
        with suppress(asyncio.CancelledError):
            await task
    if task_cron:
        with suppress(asyncio.CancelledError):
            await task_cron

    try:
        await app.state.backend.stop()
    except asyncio.CancelledError:
        pass

    try:
        await Launchy.stop()
    except asyncio.CancelledError:
        pass

    logger.info("molior shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Molior REST API",
        description="Molior Debian build system REST API.",
        version=MOLIOR_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from .routers import api_v1, api_v2
    app.include_router(api_v1.router)
    app.include_router(api_v2.router)

    return app
