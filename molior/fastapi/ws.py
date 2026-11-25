"""
Real-time channels
==================

GET /api/events
    Server-Sent Events (SSE) — alternative push channel for clients that
    prefer EventSource over WebSocket.

WS /api/websocket
    Single WebSocket endpoint, preserving the original cirrina design.
    Needs a login, like in cirrina: the session cookie (or the
    X-MoliorToken header) is checked when the client connects.
    Without a valid login the server sends {"status": 401} and closes the
    connection with code 4401 (the web UI logs out on that message).
    The same happens to an open connection when the sessions of the user
    end (logout in any browser, user deleted, password changed), when its
    session expires, and when the token is deleted (checked every
    LOGIN_RECHECK_INTERVAL seconds).
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
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from .auth import authenticated, get_current_user, session_expiry, CurrentUser
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
_MSG_UNAUTHORIZED = json.dumps({"status": 401})

WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_INTERNAL_ERROR = 1011


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
# Authentication of a WebSocket connection
# ---------------------------------------------------------------------------

# seconds between two checks of the login of an open connection (deleted user or token)
LOGIN_RECHECK_INTERVAL = 60


def websocket_user(websocket: WebSocket) -> CurrentUser | None:
    """
    Returns the user of the WebSocket connection, or None without a valid login.

    Uses the same session cookie and token header as the HTTP handlers. The
    DB session is closed right away, so an open connection holds no DB
    connection.
    """
    with Session() as session:
        return get_current_user(
            molior_session=websocket.cookies.get("molior_session"),
            x_molior_token=websocket.headers.get("x-moliortoken"),
            db=session,
        )


class _Connection:
    """An open, logged in WebSocket connection."""

    def __init__(self, websocket: WebSocket, user: CurrentUser, notify_q: asyncio.Queue):
        self.websocket = websocket
        self.user = user
        self.cookie = websocket.cookies.get("molior_session")
        self.notify_q = notify_q
        self.logged_out = asyncio.Event()

    def logout(self):
        """No notification is queued for the connection any more; the handler sends 401 and closes."""
        _ws_queues.discard(self.notify_q)
        self.logged_out.set()


_ws_connections: set = set()    # set[_Connection]
_loop: asyncio.AbstractEventLoop | None = None     # the event loop of the connections


def close_user_connections(username: str) -> int:
    """
    Called when the login sessions of a user end (logout, user deleted,
    password changed): the open WebSocket connections of the user get
    {"status": 401} and are closed. Returns the number of connections.
    Can be called from the event loop and from the threads of sync handlers.
    """
    found = [c for c in list(_ws_connections) if c.user.username == username]
    if not found:
        return 0
    try:
        in_loop = asyncio.get_running_loop() is _loop
    except RuntimeError:
        in_loop = False
    for conn in found:
        if in_loop:
            conn.logout()
        else:
            _loop.call_soon_threadsafe(conn.logout)
    return len(found)


def _session_expiry(cookie: str) -> float | None:
    with Session() as session:
        return session_expiry(session, cookie)


async def _watch_login(conn: _Connection) -> str:
    """
    Ends when the login of the connection is no longer valid, returns the reason:
    logout (close_user_connections), the session expired, or the session, user
    or token is gone (checked every LOGIN_RECHECK_INTERVAL seconds, also finds
    a logout in another server process). A DB error during a check keeps the
    connection.
    """
    expiry = None
    if conn.user.auth_token is None and conn.cookie:
        try:
            expiry = _session_expiry(conn.cookie)
        except Exception as exc:
            logger.error("ws: cannot read the session expiry of user %s: %s", conn.user.username, exc)
    while True:
        timeout = LOGIN_RECHECK_INTERVAL
        if expiry is not None:
            timeout = max(0, min(timeout, expiry - time.time()))
        try:
            await asyncio.wait_for(conn.logged_out.wait(), timeout=timeout)
            return "sessions of the user ended"
        except asyncio.TimeoutError:
            pass
        if expiry is not None and time.time() >= expiry:
            return "session expired"
        try:
            if not websocket_user(conn.websocket):
                return "login no longer valid"
        except Exception as exc:
            logger.error("ws: cannot check the login of user %s: %s", conn.user.username, exc)


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
    When the sessions of the user end, the session expires, or the token is
    deleted, the server sends {"status": 401} and closes the connection (4401).
    """
    global _loop
    _loop = asyncio.get_running_loop()
    await websocket.accept()

    try:
        user = websocket_user(websocket)
    except Exception as exc:
        logger.error("ws: cannot check the login: %s", exc)
        await websocket.close(code=WS_CLOSE_INTERNAL_ERROR)
        return

    if not user:
        logger.info("ws: connection without a valid login refused")
        with contextlib.suppress(Exception):
            await websocket.send_text(_MSG_UNAUTHORIZED)
            await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return

    logger.debug("ws: new connection from user %s", user.username)
    await websocket.send_text(_MSG_CONNECTED)

    # Per-connection notification queue — broadcast() will put payloads here
    notify_q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _ws_queues.add(notify_q)
    conn = _Connection(websocket, user, notify_q)
    _ws_connections.add(conn)

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

    async def _receive_messages():
        """Handles the messages of the client, returns when the client disconnects."""
        nonlocal logger_task, active_logger
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send a keepalive ping to prevent idle connection drops.
                with contextlib.suppress(Exception):
                    await websocket.send_text('{"subject":1,"event":5}')
                continue
            except WebSocketDisconnect:
                return

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
                logger.debug("ws: user %s starts the log stream of build %s", user.username, build_id)
                active_logger = _BuildLogger(websocket.send_text, int(build_id))
                logger_task = asyncio.create_task(active_logger.run())

            elif action == Action.stop.value:
                await _stop_logger()

            else:
                logger.warning("ws: unknown action %s", action)

    push_task = asyncio.create_task(_push_notifications())
    receive_task = asyncio.create_task(_receive_messages())
    watch_task = asyncio.create_task(_watch_login(conn))
    reason = None

    try:
        await asyncio.wait({receive_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        if watch_task.done() and not watch_task.cancelled() and watch_task.exception() is None:
            reason = watch_task.result()
    finally:
        _ws_connections.discard(conn)
        _ws_queues.discard(notify_q)
        for task in (receive_task, watch_task, push_task):
            task.cancel()
        results = await asyncio.gather(receive_task, watch_task, push_task, return_exceptions=True)
        for result in results[:2]:
            if isinstance(result, Exception):
                logger.error("ws: connection of user %s failed: %s", user.username, result)
        if isinstance(results[2], WebSocketDisconnect):
            # the push task ended because sending to the closed connection failed
            logger.warning("ws: client disconnected")
        await _stop_logger()

    if reason:
        # no notification or log data is sent after this message
        logger.info("ws: closing the connection of user %s: %s", user.username, reason)
        with contextlib.suppress(Exception):
            await websocket.send_text(_MSG_UNAUTHORIZED)
            await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
