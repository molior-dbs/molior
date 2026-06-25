"""
FastAPI application factory.

Replaces cirrina/aiohttp as the HTTP layer.  Owns the full server lifecycle:
workers, backend init, and cron scheduling (previously in MoliorServer).

Only /api2/ routes are active.  /api/ v1 and WebSockets will be added in
later iterations.
"""

import asyncio
from contextlib import asynccontextmanager, suppress

from async_cron.job import CronJob
from async_cron.schedule import Scheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from launchy import Launchy

from ..auth.auth import Auth
from ..logger import logger
from ..model.database import Session
from ..model.metadata import MetaData
from ..molior.backend import Backend
from ..molior.queues import enqueue_aptly
from ..molior.worker import Worker
from ..molior.worker_aptly import AptlyWorker
from ..molior.worker_backend import BackendWorker
from ..molior.worker_notification import NotificationWorker
from ..version import MOLIOR_VERSION


def _get_weekday_number(name):
    return {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6}.get(name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .auth import assert_secret_configured
    assert_secret_configured()
    logger.info("starting molior v%s (fastapi)", MOLIOR_VERSION)

    backend = Backend().init()
    if not backend:
        raise RuntimeError("Backend init failed")
    if not Auth().init():
        raise RuntimeError("Auth init failed")

    # Launchy.attach_loop() calls asyncio.SafeChildWatcher() which needs a
    # running loop.  We're inside the lifespan coroutine so the loop is live.
    Launchy.attach_loop(asyncio.get_running_loop())

    task_worker = asyncio.ensure_future(Worker().run())
    task_aptly = asyncio.ensure_future(AptlyWorker().run())
    task_backend = asyncio.ensure_future(BackendWorker().run())
    from .ws import broadcast
    task_notification = asyncio.ensure_future(NotificationWorker().run(broadcast))

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
                    job.every().weekday(_get_weekday_number(weekday)).at(cleanup_time.value).go(
                        lambda: asyncio.ensure_future(enqueue_aptly({"cleanup": []}))
                    )
                    sched.add_job(job)
                task_cron = asyncio.ensure_future(sched.start())
            else:
                logger.info("cleanup job disabled")
        else:
            logger.error("cleanup job metadata not set")

    yield  # ---- application is running ----

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
        await backend.stop()
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
        docs_url="/api2/docs",
        redoc_url="/api2/redoc",
        openapi_url="/api2/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .routers.api_v1 import router as v1_router
    from .routers.api_v2 import router as v2_router
    from .ws import router as ws_router
    app.include_router(v1_router)
    app.include_router(v2_router)
    app.include_router(ws_router)

    return app
