"""main_websocket: login check at connect, and a client which disconnects while a notification is sent."""
import asyncio
import importlib.util
import sys
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
    def __init__(self, username):
        self.username = username


def fake_get_current_user(molior_session=None, x_molior_token=None, db=None):
    """Like auth.get_current_user: a user for a valid cookie or token, None otherwise."""
    if molior_session == "valid":
        return CurrentUser("alice")
    if x_molior_token == "valid-token":
        return CurrentUser("__token__")
    return None


@pytest.fixture
def ws():
    logger = MagicMock()
    auth = MagicMock(CurrentUser=CurrentUser)
    auth.get_current_user = MagicMock(side_effect=fake_get_current_user)
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
