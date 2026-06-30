"""
Real-time channels
==================

GET /api/events
    Server-Sent Events (SSE) — alternative push channel for clients that
    prefer EventSource over WebSocket.

WS /api/websocket
    Single WebSocket endpoint, preserving the original cirrina design.
    The server pushes build/mirror/userrole change notifications to every
    connected client (same as cirrina's websocket_broadcast).
    The client may additionally request build-log streaming:
        → {"subject": 8, "action": 4, "data": {"build_id": <int>}}   start
        → {"subject": 8, "action": 5}                                  stop
        ← {"subject": 8, "event": 1, "data": "<chunk>"}               log data
        ← {"subject": 8, "event": 5}                                   done
    Connected event on both channels:
        ← {"subject": 1, "event": 4}

WS /internal/buildlog/{token}
    Used by build agents to stream log lines into the server.
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
# Shared broadcast hub — fans out to SSE subscribers AND WebSocket connections
# ---------------------------------------------------------------------------

_sse_queues: set = set()    # set[asyncio.Queue]  one per SSE client
_ws_queues: set = set()     # set[asyncio.Queue]  one per WebSocket client

_MSG_CONNECTED = json.dumps({"subject": Subject.websocket.value, "event": Event.connected.value})
_MSG_BUILDLOG_DONE = json.dumps({"subject": Subject.buildlog.value, "event": Event.done.value})


async def broadcast(msg: dict):
    """
    Fan a notification dict out to every connected SSE client and every
    connected WebSocket client.  Called by NotificationWorker and any
    handler that emits inline events (e.g. userrole changes).
    """
    payload = json.dumps(msg)
    dead: set = set()

    for q in list(_sse_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_queues.difference_update(dead)

    dead = set()
    for q in list(_ws_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _ws_queues.difference_update(dead)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

async def _sse_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _sse_queues.add(q)
    try:
        yield f"data: {_MSG_CONNECTED}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(q.get(), timeout=20)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        _sse_queues.discard(q)


@router.get("/api/events")
async def sse_events(
    request: Request,
    _: CurrentUser = Depends(authenticated),
):
    """Server-Sent Events — push notifications without a WebSocket."""
    return StreamingResponse(
        _sse_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Build-log streaming helper
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


# ---------------------------------------------------------------------------
# Main WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/api/websocket")
async def main_websocket(websocket: WebSocket):
    """
    Single WebSocket endpoint.

    On connect the server sends a 'connected' event.
    The server pushes all build/mirror/userrole notifications to the client
    via a per-connection asyncio queue (same fan-out as SSE).
    The client may start/stop a build-log stream by sending action messages.
    """
    await websocket.accept()
    await websocket.send_text(_MSG_CONNECTED)

    # Per-connection notification queue — broadcast() will put payloads here
    notify_q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _ws_queues.add(notify_q)

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

    async def _push_notifications():
        """Forward broadcast payloads to this WebSocket."""
        while True:
            payload = await notify_q.get()
            await websocket.send_text(payload)

    push_task = asyncio.create_task(_push_notifications())

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send a keepalive ping to prevent idle connection drops.
                with contextlib.suppress(Exception):
                    await websocket.send_text('{"subject":1,"event":5}')
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.error("ws: invalid JSON from client")
                continue

            subject = msg.get("subject")
            action = msg.get("action")

            if subject != Subject.buildlog.value:
                logger.warning("ws: unexpected subject %s", subject)
                continue

            if action == Action.start.value:
                await _stop_logger()
                build_id = (msg.get("data") or {}).get("build_id")
                if not build_id:
                    logger.error("ws: start message missing build_id")
                    continue
                logger.debug("ws: starting log stream for build %s", build_id)
                active_logger = _BuildLogger(websocket.send_text, int(build_id))
                logger_task = asyncio.create_task(active_logger.run())

            elif action == Action.stop.value:
                await _stop_logger()

            else:
                logger.warning("ws: unknown action %s", action)

    except WebSocketDisconnect:
        pass
    finally:
        _ws_queues.discard(notify_q)
        push_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await push_task
        await _stop_logger()
