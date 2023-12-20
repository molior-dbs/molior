import cirrina
import click
import signal
import functools
import asyncio

from .molior.server import MoliorServer
from ..logger import logger
from ..version import MOLIOR_VERSION

app = MoliorServer("127.0.0.1", 9999, session_type=cirrina.Server.SessionType.FILE, session_dir="/var/lib/molior/web-sessions/")
app.title = "Molior REST API Documentation"
app.description = "Documentation of the molior REST API."
app.api_version = 1
app.contact = ""

# import api handlers
from .auth.auth import Auth          # noqa: F401
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
import molior.api2.admin             # noqa: F401


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
    moliorserver = MoliorServer(loop, host, port, debug=debug)

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
