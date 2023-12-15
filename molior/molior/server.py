import asyncio
import click
import signal
import functools
import cirrina

from sqlalchemy.orm import sessionmaker
from launchy import Launchy
from async_cron.job import CronJob
from async_cron.schedule import Scheduler

from molior.model.metadata import MetaData

from ..logger import logger
from ..version import MOLIOR_VERSION
from ..model.database import database, Session
from .configuration import Configuration

from .worker import Worker
from .worker_aptly import AptlyWorker
from .worker_backend import BackendWorker
from .worker_notification import NotificationWorker
from .backend import Backend
from ..auth.auth import Auth


async def run_molior(self):
    logger.info("MoliorServer: run")
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
    self.task_notification_worker = asyncio.ensure_future(notification_worker.run(self))

    cfg = Configuration()
    cleanup_active = cfg.cleanup.get("cleanup_active")
    cleanup_weekday = cfg.cleanup.get("cleanup_weekday")
    cleanup_time = cfg.cleanup.get("cleanup_time")

    def get_weekday_number(weekday_name):
        weekday_mapping = {
            'Monday': 0,
            'Tuesday': 1,
            'Wednesday': 2,
            'Thursday': 3,
            'Friday': 4,
            'Saturday': 5,
            'Sunday': 6
        }
        return weekday_mapping.get(weekday_name)

    if not cleanup_time:
        cleanup_time = "04:00"
    if not cleanup_weekday:
        cleanup_weekday = 'Sunday'

    if cleanup_active is False or cleanup_active == "off" or cleanup_active == "disabled":
        self.logger.info("cleanup job disabled")
        return
    else:
        self.logger.info(f"cleanup job enabled for every {cleanup_weekday} at {cleanup_time}")

    cleanup_sched = Scheduler(locale="en_US")
    cleanup_job = CronJob(name='cleanup').every().weekday(get_weekday_number(
        cleanup_weekday)).at(cleanup_time).go(self.cleanup_task)
    cleanup_sched.add_job(cleanup_job)
    self.task_cron = asyncio.ensure_future(cleanup_sched.start())

    # self.run(self.host, self.port, logger=self.logger, debug=self.debug)


class MoliorServer(cirrina.Server):

    def __init__(self, host, port, session_type=None, session_dir=None):
        super().__init__(session_type=session_type, session_dir=session_dir, session_max_age=302400)  # 1 week sessions
        self.task_worker = None
        self.task_backend_worker = None
        self.task_aptly_worker = None
        self.task_notification_worker = None
        self.task_cron = None

        self.set_context_functions(MoliorServer.create_cirrina_context, MoliorServer.destroy_cirrina_context)
        self.on_startup.append(run_molior)

    def list_active_tasks(self, debug_pos):
        logger.info(debug_pos)
        tasks = asyncio.all_tasks()
        logger.info(f"There are {len(tasks)} active tasks")
        task_ids = [id(task) for task in tasks]  # Get the IDs of all tasks
        logger.info("Active Task IDs: %s", task_ids)
        logger.info("Start of tasks listed: ")
        for task in tasks:
            logger.info(task.get_name())
            logger.info(task.get_coro())
        logger.info("End of tasks listed: ")

    def get_weekday_number(self, weekday_name):
        weekday_mapping = {
            'Monday': 0,
            'Tuesday': 1,
            'Wednesday': 2,
            'Thursday': 3,
            'Friday': 4,
            'Saturday': 5,
            'Sunday': 6
        }
        return weekday_mapping.get(weekday_name)

    @staticmethod
    def create_cirrina_context(cirrina):
        maker = sessionmaker(bind=database.engine)
        cirrina.add_context("db_session", maker())

    @staticmethod
    def destroy_cirrina_context(cirrina):
        cirrina.db_session.close()

    async def cleanup_task(self):
        await self.enqueue_aptly({"cleanup": []})

    def weekly_cleanup(self):
        if hasattr(self, 'task_cron') and self.task_cron:
            # If a scheduler already exists, cancel the existing tasks
            self.task_cron.cancel()

        # extract values from db or write default values a new molior-server instance
        cleanup_weekdays_list = []
        with Session() as session:
            cleanup_active = session.query(MetaData).filter_by(
                name="cleanup_active").first()
            cleanup_weekdays = session.query(MetaData).filter_by(
                name="cleanup_weekdays").first()
            cleanup_time = session.query(MetaData).filter_by(
                name="cleanup_time").first()

            if cleanup_active is None or cleanup_weekdays is None or cleanup_time is None:
                logger.error("cleanup job not set")
            else:
                if cleanup_active.value.lower() == "false":
                    logger.info("cleanup job disabled")
                    return
                else:
                    cleanup_sched = Scheduler(locale="en_US")
                    cleanup_weekdays_list = cleanup_weekdays.value.split(',')

                    # create single cleanup_job for every weekday
                    for weekday in cleanup_weekdays_list:
                        logger.info(f"cleanup job enabled for every {weekday} at {cleanup_time.value}")
                        cleanup_job = CronJob(name=f'cleanup_{weekday}')
                        cleanup_job.every().weekday(self.get_weekday_number(weekday)).at(cleanup_time.value).go(self.cleanup_task)
                        cleanup_sched.add_job(cleanup_job)

                    self.task_cron = asyncio.ensure_future(cleanup_sched.start())

    async def terminate(self):

        self.list_active_tasks(debug_pos="At the beginning of the terminate function:")

        self.logger.info("terminating tasks")

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
            self.logger.info("tasks were canceled")
        else:
            self.logger.info("tasks were completed")

        try:
            self.logger.info("terminating backend")
            await self.backend.stop()
        except asyncio.CancelledError:
            self.logger.info("backend tasks were completed")

        try:
            self.logger.info("terminating launchy")
            await Launchy.stop()
        except asyncio.CancelledError:
            self.logger.info("launchy tasks were completed")

        self.list_active_tasks(debug_pos="At the end of the terminate function:")

        self.logger.info("terminating app")
        self.stop()


@click.command()
@click.option("--host",     default="localhost",         help="Hostname, examples: 'localhost' or '0.0.0.0'")
@click.option("--port",     default=8888,                help="Listen port")
@click.option("--debug",    default=False, is_flag=True, help="Enable debug")
@click.option("--coverage", default=False, is_flag=True, help="Enable coverage testing")
def main(host, port, debug, coverage):
    logger.info("starting molior v%s", MOLIOR_VERSION)

    if coverage:
        # logger.warning("starting coverage measurement")
        import coverage
        cov = coverage.Coverage(source=["molior"])
        cov.start()

    loop = asyncio.get_event_loop()
    moliorserver = MoliorServer(loop, host, port, logger=logger, debug=debug)

    def terminate(signame):
        moliorserver.logger.info("received %s, terminating...", signame)
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
        moliorserver.logger.warning("saving coverage measurement")
        cov.stop()
        cov.html_report(directory='/var/lib/molior/buildout/coverage')

    moliorserver.logger.info("terminated")


if __name__ == "__main__":
    main()
