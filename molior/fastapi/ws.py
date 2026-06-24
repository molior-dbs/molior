"""
Real-time channels
==================

GET /api/events
    Server-Sent Events (SSE) for push notifications.
    Replaces the broadcast half of the cirrina single-WebSocket design.
    The browser uses EventSource('/api/events').

WS /api/websocket
    WebSocket for build-log streaming only.
    Keeps the same URL so the existing nginx WebSocket proxy block works.
    Protocol (client → server):
        {"subject": "buildlog", "action": "start", "data": {"build_id": <int>}}
        {"subject": "buildlog", "action": "stop"}
    Protocol (server → client):
        {"subject": "buildlog", "event": "added",  "data": "<log chunk>"}
        {"subject": "buildlog", "event": "done"}
        {"subject": "websocket", "event": "connected"}
"""

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from .auth import authenticated, CurrentUser
from ..logger import logger
from ..model.build import Build
from ..model.database import Session
from ..molior.notifier import Subject, Event, Action

router = APIRouter()

# ---------------------------------------------------------------------------
# SSE broadcast hub
# ---------------------------------------------------------------------------

_subscribers: set = set()   # set[asyncio.Queue]


async def broadcast(msg: dict):
    """
    Fan a notification out to all connected SSE clients.
    Called by NotificationWorker and any handler that emits events
    (e.g. userrole changes).
    """
    dead = set()
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.add(q)
    _subscribers.difference_update(dead)


# Pre-built constant messages (integers match the frontend enum values)
_MSG_CONNECTED = json.dumps({"subject": Subject.websocket.value, "event": Event.connected.value})
_MSG_BUILDLOG_DONE = json.dumps({"subject": Subject.buildlog.value, "event": Event.done.value})


async def _sse_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(q)
    try:
        yield f"data: {_MSG_CONNECTED}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20)
                yield f"data: {json.dumps(msg)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        _subscribers.discard(q)


@router.get("/api/events")
async def sse_events(
    request: Request,
    _: CurrentUser = Depends(authenticated),
):
    """
    Server-Sent Events endpoint.
    Pushes build, mirror and userrole change notifications to the browser.
    X-Accel-Buffering: no disables nginx proxy buffering without needing
    a config change in the web image.
    """
    return StreamingResponse(
        _sse_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Build-log WebSocket
# ---------------------------------------------------------------------------

_TERMINAL_STATES = frozenset({
    "build_failed", "publish_failed", "successful",
    "already_exists", "already_failed", "nothing_done",
})

BUILD_OUT_PATH = Path("/var/lib/molior/buildout")


class _BuildLogger:
    def __init__(self, send_text, build_id: int):
        self._send = send_text
        self._build_id = build_id
        self._running = False

    def stop(self):
        self._running = False

    def _is_done(self) -> bool:
        with Session() as session:
            build = session.query(Build).filter(Build.id == self._build_id).first()
            return (not build) or (build.buildstate in _TERMINAL_STATES)

    async def run(self):
        from aiofile import AIOFile, Reader

        self._running = True
        filepath = BUILD_OUT_PATH / str(self._build_id) / "build.log"
        while self._running:
            try:
                async with AIOFile(str(filepath), "rb") as f:
                    reader = Reader(f, chunk_size=16384)
                    ticks = 0
                    while self._running:
                        async for chunk in reader:
                            msg = {
                                "subject": Subject.buildlog.value,
                                "event": Event.added.value,
                                "data": chunk.decode("utf-8", errors="ignore"),
                            }
                            await self._send(json.dumps(msg))
                        # EOF — poll until build finishes or we're stopped
                        ticks += 1
                        if ticks % 100 == 0:
                            ticks = 0
                            if self._is_done():
                                self.stop()
                                break
                        await asyncio.sleep(0.1)
            except FileNotFoundError:
                await asyncio.sleep(1)
                if self._is_done():
                    self.stop()
            except Exception as exc:
                logger.error("buildlogger %d: %s", self._build_id, exc)
                self.stop()

        with contextlib.suppress(Exception):
            await self._send(_MSG_BUILDLOG_DONE)


@router.websocket("/api/websocket")
async def buildlog_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for build-log streaming.

    The client sends a start message to begin tailing a build log,
    and a stop message (or simply disconnects) to end it.
    Only one active build log stream per connection is supported.
    """
    await websocket.accept()
    await websocket.send_text(_MSG_CONNECTED)

    logger_task: asyncio.Task | None = None
    active_logger: _BuildLogger | None = None

    async def _stop_logger():
        nonlocal logger_task, active_logger
        if active_logger:
            active_logger.stop()
        if logger_task:
            logger_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await logger_task
        logger_task = None
        active_logger = None

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                continue  # keepalive — client still connected

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.error("buildlog ws: invalid JSON from client")
                continue

            subject = msg.get("subject")
            action = msg.get("action")

            if subject != Subject.buildlog.value:
                logger.warning("buildlog ws: unexpected subject %s", subject)
                continue

            if action == Action.start.value:
                await _stop_logger()
                build_id = (msg.get("data") or {}).get("build_id")
                if not build_id:
                    logger.error("buildlog ws: start message missing build_id")
                    continue
                logger.debug("buildlog ws: starting stream for build %s", build_id)
                active_logger = _BuildLogger(websocket.send_text, int(build_id))
                logger_task = asyncio.create_task(active_logger.run())

            elif action == Action.stop.value:
                await _stop_logger()

            else:
                logger.warning("buildlog ws: unknown action %s", action)

    except WebSocketDisconnect:
        pass
    finally:
        await _stop_logger()
