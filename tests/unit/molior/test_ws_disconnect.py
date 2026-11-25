"""main_websocket: login check at connect and while connected (logout, expiry, deleted user), and a client which
disconnects while a notification is sent."""
import asyncio
import importlib.util
import sys
import time
import types
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest


class WebSocketDisconnect(Exception):
    def __init__(self, code=1000):
        super().__init__(code)
        self.code = code


class FakeRouter:
    def get(self, *args, **kwargs):
        return lambda f: f

    websocket = post = put = delete = get


class Subject(Enum):
    websocket = 1
    build = 7
    buildlog = 8


class Event(Enum):
    changed = 2
    connected = 4
    done = 5
    added = 1


class Action(Enum):
    start = 1
    stop = 2


class FakeWebSocket:
    """After the first message ("connected") send_text fails like starlette does when the client is gone."""
    def __init__(self, fail_send=True, incoming=(), cookies=None, headers=None):
        self.fail_send = fail_send
        self.incoming = list(incoming)
        self.sent = []
        self.gone = asyncio.Event()
        self.cookies = {"molior_session": "valid"} if cookies is None else cookies
        self.headers = headers or {}
        self.closed = None

    async def close(self, code=1000):
        self.closed = code

    async def accept(self):
        pass

    async def send_text(self, text):
        if self.fail_send and self.sent:
            self.gone.set()
            raise WebSocketDisconnect(code=1006)
        self.sent.append(text)

    async def receive_text(self):
        if self.incoming:
            return self.incoming.pop(0)
        await self.gone.wait()
        raise WebSocketDisconnect(code=1006)


class CurrentUser:
    def __init__(self, username, auth_token=None):
        self.username = username
        self.auth_token = auth_token


# session cookies get_current_user accepts and their user (a test may remove one: session ended, user deleted)
VALID = {"valid": "alice", "valid-2": "alice", "bob-session": "bob"}


def fake_get_current_user(molior_session=None, x_molior_token=None, db=None):
    """Like auth.get_current_user: a user for a valid cookie or token, None otherwise."""
    if x_molior_token == "valid-token":
        return CurrentUser("__token__", auth_token="hashed")
    if molior_session in VALID:
        return CurrentUser(VALID[molior_session])
    return None


@pytest.fixture
def ws():
    logger = MagicMock()
    auth = MagicMock(CurrentUser=CurrentUser)
    auth.get_current_user = MagicMock(side_effect=fake_get_current_user)
    auth.session_expiry = MagicMock(return_value=time.time() + 3600)    # (db, cookie)
    VALID.clear()
    VALID.update({"valid": "alice", "valid-2": "alice", "bob-session": "bob"})
    package = types.ModuleType("molior.fastapi")
    package.__path__ = ["molior/fastapi"]
    stubs = {
        "fastapi": MagicMock(APIRouter=FakeRouter, WebSocket=object, WebSocketDisconnect=WebSocketDisconnect),
        "fastapi.responses": MagicMock(),
        "starlette": MagicMock(),
        "starlette.requests": MagicMock(),
        "molior.fastapi": package,
        "molior.fastapi.auth": auth,
        "molior.logger": MagicMock(logger=logger),
        "molior.model": MagicMock(),
        "molior.model.build": MagicMock(),
        "molior.model.database": MagicMock(),
        "molior.molior": MagicMock(),
        "molior.molior.notifier": MagicMock(Subject=Subject, Event=Event, Action=Action),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("molior.fastapi.ws", "molior/fastapi/ws.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["molior.fastapi.ws"] = module
        spec.loader.exec_module(module)
        module.auth = auth
        yield module, logger
        sys.modules.pop("molior.fastapi.ws", None)


def run(module, websocket, broadcast):
    """Runs main_websocket, optionally pushes one notification to it. Returns when the handler has ended."""
    async def main():
        task = asyncio.create_task(module.main_websocket(websocket))
        for _ in range(5):
            await asyncio.sleep(0)
        if broadcast:
            for q in list(module._ws_queues):
                q.put_nowait('{"subject": 7}')
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(main())


def test_send_to_closed_client_is_only_a_warning(ws):
    """The handler ends without an exception, with one warning and no traceback."""
    module, logger = ws
    run(module, FakeWebSocket(), broadcast=True)
    logger.warning.assert_called_once_with("ws: client disconnected")
    logger.exception.assert_not_called()
    assert module._ws_queues == set()


def test_log_stream_is_stopped_when_push_task_failed(ws):
    """The raise in the push task must not skip _stop_logger()."""
    module, logger = ws
    stopped = []

    class BuildLogger:
        def __init__(self, send, build_id):
            pass

        def stop(self):
            stopped.append(True)

        async def run(self):
            await asyncio.sleep(10)

    module._BuildLogger = BuildLogger
    start = '{"subject": %d, "action": %d, "data": {"build_id": 5}}' % (Subject.buildlog.value, Action.start.value)
    run(module, FakeWebSocket(incoming=[start]), broadcast=True)
    assert stopped == [True]
    logger.warning.assert_called_once_with("ws: client disconnected")


def test_normal_disconnect_does_not_warn(ws):
    """The client leaves while nothing is sent to it: no warning."""
    module, logger = ws
    websocket = FakeWebSocket()
    websocket.gone.set()
    run(module, websocket, broadcast=False)
    logger.warning.assert_not_called()
    assert module._ws_queues == set()


def test_connection_without_cookie_is_refused(ws):
    """No session cookie: a 401 message, close code 4401, no notifications, not registered for broadcasts."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False, cookies={})
    run(module, websocket, broadcast=True)
    assert websocket.sent == ['{"status": 401}']
    assert websocket.closed == 4401
    assert module._ws_queues == set()
    logger.info.assert_called_once_with("ws: connection without a valid login refused")


def test_connection_with_invalid_cookie_is_refused(ws):
    """A cookie that get_current_user does not accept (bad signature, expired, unknown user)."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False, cookies={"molior_session": "forged"})
    run(module, websocket, broadcast=False)
    assert websocket.sent == ['{"status": 401}']
    assert websocket.closed == 4401
    kwargs = module.auth.get_current_user.call_args.kwargs
    assert kwargs["molior_session"] == "forged"
    assert kwargs["x_molior_token"] is None


def test_refused_client_cannot_start_a_log_stream(ws):
    """A start message of a client without login is never read."""
    module, logger = ws
    started = []

    class BuildLogger:
        def __init__(self, send, build_id):
            started.append(build_id)

    module._BuildLogger = BuildLogger
    start = '{"subject": %d, "action": %d, "data": {"build_id": 5}}' % (Subject.buildlog.value, Action.start.value)
    websocket = FakeWebSocket(fail_send=False, cookies={}, incoming=[start])
    run(module, websocket, broadcast=False)
    assert started == []
    assert websocket.incoming == [start]


def test_connection_with_valid_cookie_is_accepted(ws):
    """A valid session cookie: the connected event and the notifications are sent."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False)

    async def main():
        task = asyncio.create_task(module.main_websocket(websocket))
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(module._ws_queues) == 1
        for q in list(module._ws_queues):
            q.put_nowait('{"subject": 7}')
        for _ in range(5):
            await asyncio.sleep(0)
        websocket.gone.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(main())
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"subject": 7}']
    assert websocket.closed is None
    logger.debug.assert_any_call("ws: new connection from user %s", "alice")


def test_connection_with_token_header_is_accepted(ws):
    """The X-MoliorToken header works like for the HTTP handlers."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False, cookies={}, headers={"x-moliortoken": "valid-token"})
    websocket.gone.set()
    run(module, websocket, broadcast=False)
    assert websocket.sent == ['{"subject": 1, "event": 4}']
    assert websocket.closed is None


def test_login_check_error_closes_without_401(ws):
    """A DB error while checking the login closes with 1011 and does not log the user out."""
    module, logger = ws
    module.auth.get_current_user.side_effect = RuntimeError("db down")
    websocket = FakeWebSocket(fail_send=False)
    run(module, websocket, broadcast=False)
    assert websocket.sent == []
    assert websocket.closed == 1011
    assert module._ws_queues == set()
    logger.error.assert_called_once()


def connected(websocket):
    """The connected event was sent and no 401."""
    return websocket.sent and websocket.sent[0] == '{"subject": 1, "event": 4}'


def run_until_closed(module, websocket, action, timeout=2):
    """Starts main_websocket, waits until it sent the connected event, runs action(), waits for the end."""
    async def main():
        task = asyncio.create_task(module.main_websocket(websocket))
        for _ in range(5):
            await asyncio.sleep(0)
        assert connected(websocket)
        result = action()
        if asyncio.iscoroutine(result):
            await result
        await asyncio.wait_for(task, timeout=timeout)

    asyncio.run(main())


def test_logout_closes_all_connections_of_the_user(ws):
    """close_user_connections(username): all connections of the user (all browsers) get 401 and 4401,
    those of other users stay open."""
    module, logger = ws
    first = FakeWebSocket(fail_send=False)
    second = FakeWebSocket(fail_send=False, cookies={"molior_session": "valid-2"})     # another browser
    other = FakeWebSocket(fail_send=False, cookies={"molior_session": "bob-session"})

    async def main():
        tasks = [asyncio.create_task(module.main_websocket(w)) for w in (first, second, other)]
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(module._ws_connections) == 3
        assert module.close_user_connections("alice") == 2
        await asyncio.wait_for(asyncio.gather(*tasks[:2]), timeout=2)
        assert not tasks[2].done()
        other.gone.set()
        await asyncio.wait_for(tasks[2], timeout=2)

    asyncio.run(main())
    for websocket in (first, second):
        assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
        assert websocket.closed == 4401
    assert other.sent == ['{"subject": 1, "event": 4}']
    assert other.closed is None
    assert module._ws_connections == set()
    assert module._ws_queues == set()


def test_close_user_without_connections(ws):
    module, logger = ws
    assert module.close_user_connections("nobody") == 0


def test_close_user_connections_from_a_thread(ws):
    """Sync handlers (user deleted, password changed) run in a thread: the logout is passed to the event loop."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False)

    async def from_thread():
        assert await asyncio.to_thread(module.close_user_connections, "alice") == 1

    run_until_closed(module, websocket, from_thread)
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
    assert websocket.closed == 4401


def test_logout_stops_notifications_and_log_stream(ws):
    """After the 401 nothing else is sent, the log stream is stopped."""
    module, logger = ws
    stopped = []

    class BuildLogger:
        def __init__(self, send, build_id):
            pass

        def stop(self):
            stopped.append(True)

        async def run(self):
            await asyncio.sleep(10)

    module._BuildLogger = BuildLogger
    start = '{"subject": %d, "action": %d, "data": {"build_id": 5}}' % (Subject.buildlog.value, Action.start.value)
    websocket = FakeWebSocket(fail_send=False, incoming=[start])

    async def logout():
        module.close_user_connections("alice")
        await module.broadcast({"subject": 7})     # a notification right after the logout

    run_until_closed(module, websocket, logout)
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
    assert stopped == [True]


def test_expired_session_is_closed(ws):
    """The session expires while connected: 401 and 4401 at the expiry time (read from the session table)."""
    module, logger = ws
    module.auth.session_expiry.return_value = time.time() + 0.2
    websocket = FakeWebSocket(fail_send=False)
    run_until_closed(module, websocket, lambda: None)
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
    assert websocket.closed == 4401
    logger.info.assert_called_with("ws: closing the connection of user %s: %s", "alice", "session expired")
    assert module.auth.session_expiry.call_args.args[1] == "valid"


def test_already_expired_cookie_is_refused_at_connect(ws):
    """get_current_user does not accept the cookie of an expired session, so no connection."""
    module, logger = ws
    websocket = FakeWebSocket(fail_send=False, cookies={"molior_session": "expired"})
    run(module, websocket, broadcast=False)
    assert websocket.sent == ['{"status": 401}']
    assert websocket.closed == 4401


def test_ended_session_is_closed_at_the_next_check(ws):
    """The session row is gone (logout in another server process, user deleted): found by the recheck."""
    module, logger = ws
    module.LOGIN_RECHECK_INTERVAL = 0.05
    websocket = FakeWebSocket(fail_send=False)
    run_until_closed(module, websocket, lambda: VALID.pop("valid"))
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
    assert websocket.closed == 4401
    logger.info.assert_called_with("ws: closing the connection of user %s: %s", "alice", "login no longer valid")


def test_token_connection_has_no_expiry_and_is_rechecked(ws):
    """Tokens do not expire; a deleted token is found at the next check."""
    module, logger = ws
    module.LOGIN_RECHECK_INTERVAL = 0.05
    websocket = FakeWebSocket(fail_send=False, cookies={}, headers={"x-moliortoken": "valid-token"})

    def delete_token():
        websocket.headers["x-moliortoken"] = "deleted"

    run_until_closed(module, websocket, delete_token)
    module.auth.session_expiry.assert_not_called()
    assert websocket.sent == ['{"subject": 1, "event": 4}', '{"status": 401}']
    assert websocket.closed == 4401


def test_db_error_during_recheck_keeps_the_connection(ws):
    module, logger = ws
    module.LOGIN_RECHECK_INTERVAL = 0.02
    websocket = FakeWebSocket(fail_send=False)

    async def db_down_then_leave():
        module.auth.get_current_user.side_effect = RuntimeError("db down")
        await asyncio.sleep(0.1)
        websocket.gone.set()

    run_until_closed(module, websocket, db_down_then_leave)
    assert websocket.sent == ['{"subject": 1, "event": 4}']
    assert websocket.closed is None
    assert logger.error.call_count >= 2
    assert module._ws_connections == set()
