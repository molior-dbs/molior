import os

from aiohttp import web
from pathlib import Path

from ..app import app, logger
from ..molior.configuration import Configuration
from ..model.database import Session
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..molior.queues import buildlog


if not os.environ.get("IS_SPHINX", False):
    config = Configuration()
    upload_dir = config.working_dir + "/upload/"
    buildout_path = Path(Configuration().working_dir) / "buildout"
else:
    upload_dir = "/non/existent"
    buildout_path = "/non/existent"


@app.http_upload("/internal/buildupload/{token}", upload_dir=upload_dir)
async def file_upload(request, tempfile, filename, size):
    token = request.match_info["token"]
    logger.debug("file uploaded: %s (%s) %dbytes, token %s", tempfile, filename, size, token)

    build_id = None
    with Session() as session:
        build = session.query(Build).join(BuildTask).filter(BuildTask.task_id == token).first()
        if not build:
            logger.error("file_upload: no build found for token '%s'", token)
            return web.Response(status=400, text="Invalid file upload.")
        build_id = build.id

    try:
        # FIXME: do not overwrite
        os.rename(tempfile, str(buildout_path / str(build_id) / filename))
    except Exception as exc:
        logger.exception(exc)

    return web.Response(text="file uploaded: {} ({} bytes)".format(filename, size))


@app.websocket_connect(group="log")
async def ws_logs_connected(ws_client):
    token = ws_client.cirrina.request.match_info["token"]

    build_id = None
    with Session() as session:
        build = session.query(Build).join(BuildTask).filter(BuildTask.task_id == token).first()
        if not build:
            logger.error("file_upload: no build found for token '%s'", token)
            # FIXME: disconnect
            return ws_client
        build_id = build.id

    logger.debug("ws: recieving logs for build {}".format(build_id))
    ws_client.cirrina.build_id = build_id
    return ws_client


@app.websocket_message("/internal/buildlog/{token}", group="log", authenticated=False)
async def ws_logs(ws_client, msg):
    await buildlog(ws_client.cirrina.build_id, msg)
    return ws_client


@app.websocket_disconnect(group="log")
async def ws_logs_disconnected(ws_client):
    logger.debug("ws: end of logs for build {}".format(ws_client.cirrina.build_id))
    await buildlog(ws_client.cirrina.build_id, None)  # signal end of logs
    return ws_client
