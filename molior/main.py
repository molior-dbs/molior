import click
import signal
import functools
import asyncio

from aiohttp import web

from .app import app
from .logger import logger


@click.command()
@click.option("--host",     default="localhost",         help="Hostname, examples: 'localhost' or '0.0.0.0'")
@click.option("--port",     default=8888,                help="Listen port")
@click.option("--debug",    default=False, is_flag=True, help="Enable debug")
@click.option("--coverage", default=False, is_flag=True, help="Enable coverage testing")
def main(host, port, debug, coverage):

    if coverage:
        # logger.warning("starting coverage measurement")
        import coverage
        cov = coverage.Coverage(source=["molior"])
        cov.start()

    loop = asyncio.get_event_loop()

    def terminate(signame):
        logger.info("received %s, terminating...", signame)
        asyncio.run_coroutine_threadsafe(app.terminate(), loop)
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

    web.run_app(app, host=host, port=port)  # server up and running ...

    if coverage:
        logger.warning("saving coverage measurement")
        cov.stop()
        cov.html_report(directory='/var/lib/molior/buildout/coverage')

    logger.info("terminated")


if __name__ == "__main__":
    main()
