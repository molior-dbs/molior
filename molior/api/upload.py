import os

from aiohttp import web
from pathlib import Path
from aiofile import AIOFile, Writer

from molior.app import app, logger
from molior.molior.configuration import Configuration
from molior.model.database import Session
from molior.model.build import Build
from molior.model.buildtask import BuildTask


if not os.environ.get("IS_SPHINX", False):
    config = Configuration()
    upload_dir = config.working_dir + "/upload/"
else:
    upload_dir = "/non/existent"


@app.http_upload("/internal/buildupload/{token}", upload_dir=upload_dir)
async def file_upload(request, tempfile, filename, size):
    token = request.match_info["token"]
    logger.debug("file uploaded: %s (%s) %dbytes, token %s", tempfile, filename, size, token)

    with Session() as session:
        build = session.query(Build).join(BuildTask).filter(BuildTask.task_id == token).first()
        if not build:
            logger.error("file_upload: no build found for token '%s'", token)
            return web.Response(status=400, text="Invalid file upload.")

        buildout_path = Path(Configuration().working_dir) / "buildout" / str(build.id)
        # FIXME: do not overwrite
        os.rename(tempfile, str(buildout_path / filename))

    return web.Response(text="file uploaded: {} ({} bytes)".format(filename, size))


def get_log_file_path(build_id):
    """Get log file path for given task_id.

        Args:
            task_id (str): The tasks's id

        Returns:
            str: Path to log file
    """
    buildout_path = Path(Configuration().working_dir) / "buildout"
    dir_path = buildout_path / str(build_id)
    # FIXME: do not create buildout directory here
    if not dir_path.is_dir():
        dir_path.mkdir(parents=True)
    full_path = dir_path / "build.log"
    return str(full_path)


@app.websocket_connect(group="log")
async def ws_logs_connected(ws_client):
    token = ws_client.cirrina.request.match_info["token"]

    with Session() as session:
        build = session.query(Build).join(BuildTask).filter(BuildTask.task_id == token).first()
        if not build:
            logger.error("file_upload: no build found for token '%s'", token)
            # FIXME: disconnect
            return ws_client

    filename = get_log_file_path(build.id)
    afp = AIOFile(filename, 'w')
    await afp.open()
    writer = Writer(afp)
    ws_client.molior.logfile = (afp, writer)
    return ws_client


@app.websocket_message("/internal/buildlog/{token}", group="log", authenticated=False)
async def ws_logs(ws_client, msg):
    afp, writer = ws_client.molior.logfile
    await writer(msg)
    await afp.fsync()
    return ws_client


@app.websocket_disconnect(group="log")
async def ws_logs_disconnected(ws_client):
    afp, _ = ws_client.molior.logfile
    await afp.fsync()
    await afp.close()
    return ws_client
