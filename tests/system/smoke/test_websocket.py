"""WebSocket smoke tests: /api/websocket needs a login, like the HTTP API."""
import json

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from moliortest import MOLIOR_URL

WS_URL = MOLIOR_URL.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/api/websocket"


def ws_connect(cookie=None):
    headers = {"Cookie": f"molior_session={cookie}"} if cookie else None
    return connect(WS_URL, additional_headers=headers, open_timeout=10)


def receive_all(ws):
    """The messages until the server closes the connection."""
    messages = []
    with pytest.raises(ConnectionClosed):
        while True:
            messages.append(json.loads(ws.recv(timeout=10)))
    return messages


def test_websocket_without_login_is_refused(public):
    with ws_connect() as ws:
        assert receive_all(ws) == [{"status": 401}]
        assert ws.close_code == 4401


def test_websocket_with_invalid_cookie_is_refused(public):
    with ws_connect("not-a-valid-session") as ws:
        assert receive_all(ws) == [{"status": 401}]
        assert ws.close_code == 4401


def test_websocket_with_login_is_connected(admin):
    with ws_connect(admin.session.cookies["molior_session"]) as ws:
        assert json.loads(ws.recv(timeout=10)) == {"subject": 1, "event": 4}
