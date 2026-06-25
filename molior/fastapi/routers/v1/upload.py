"""
Internal endpoints used by build agents:

  POST /internal/buildupload/{token}
      Multipart file upload (curl -F "file=@foo.deb").
      Moves the received file into buildout/{build_id}/{filename}.

  WS /internal/buildlog/{token}
      The build agent streams log lines as plain text WebSocket messages.
      Each message is written to the build log via the buildlog queue.
      A None sentinel (on disconnect) signals end-of-log to the backend.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect

from ....logger import logger
from ....model.build import Build
from ....model.buildtask import BuildTask
from ....model.database import Session
from ....molior.configuration import Configuration
from ....molior.queues import buildlog

router = APIRouter(tags=["internal"])


def _token_hint(token: str) -> str:
    """Return a short identifier safe for logs — never the raw token value."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


_config = Configuration()
_upload_dir = Path(_config.working_dir) / "upload"
_buildout_path = Path(_config.working_dir) / "buildout"


def _build_id_for_token(token: str):
    """Look up the build id for a given task token. Returns None if not found."""
    with Session() as session:
        build = session.query(Build).join(BuildTask).filter(BuildTask.task_id == token).first()
        return build.id if build else None


@router.post("/internal/buildupload/{token}")
async def file_upload(token: str, file: UploadFile = File(...)):
    """
    Receive one build artefact (.deb, .changes, .buildinfo, …) from the build agent.
    The agent calls this once per file with:  curl -F "file=@<path>" http://…/internal/buildupload/<token>
    """
    build_id = _build_id_for_token(token)
    if build_id is None:
        logger.error("buildupload: no build found for token hint=%s", _token_hint(token))
        raise HTTPException(status_code=400, detail="Invalid upload token")

    dest_dir = _buildout_path / str(build_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(file.filename).name   # strip any directory components

    # Stream via a named temp file in the same filesystem to allow atomic rename
    _upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=_upload_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1 << 20)  # 1 MiB chunks
                if not chunk:
                    break
                tmp.write(chunk)
        shutil.move(str(tmp_path), str(dest))
    except Exception as exc:
        logger.exception(exc)
        raise HTTPException(status_code=500, detail="Upload failed")

    logger.debug("buildupload: build %d received %s (%d bytes)", build_id, file.filename, dest.stat().st_size)
    return f"file uploaded: {file.filename}"


@router.websocket("/internal/buildlog/{token}")
async def buildlog_ws(websocket: WebSocket):
    """
    The build agent connects here and sends log lines as plain text WebSocket frames.
    We feed them into the buildlog queue which writes them to build.log and
    forwards them to the SSE/WS log-streaming clients.
    A disconnect (or an explicit None) signals end-of-log to the backend worker.
    """
    await websocket.accept()

    token = websocket.path_params["token"]
    build_id = _build_id_for_token(token)
    if build_id is None:
        logger.error("buildlog ws: no build found for token hint=%s", _token_hint(token))
        await websocket.close(code=4400)
        return

    logger.debug("buildlog ws: receiving logs for build %d", build_id)
    try:
        while True:
            msg = await websocket.receive_text()
            await buildlog(build_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        logger.debug("buildlog ws: end of logs for build %d", build_id)
        await buildlog(build_id, None)  # signal end of logs to backend
