"""main_websocket: a client which disconnects while a notification is sent is only a warning."""
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
    def __init__(self, fail_send=True, incoming=()):
        self.fail_send = fail_send
        self.incoming = list(incoming)
        self.sent = []
        self.gone = asyncio.Event()

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


@pytest.fixture
def ws():
    logger = MagicMock()
    package = types.ModuleType("molior.fastapi")
    package.__path__ = ["molior/fastapi"]
    stubs = {
        "fastapi": MagicMock(APIRouter=FakeRouter, WebSocket=object, WebSocketDisconnect=WebSocketDisconnect),
        "fastapi.responses": MagicMock(),
        "starlette": MagicMock(),
        "starlette.requests": MagicMock(),
        "molior.fastapi": package,
        "molior.fastapi.auth": MagicMock(),
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
