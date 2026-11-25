"""WebSocket smoke tests: /api/websocket needs a login, like the HTTP API."""
import json

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from moliortest import Api, ADMIN_PASSWORD, MOLIOR_URL

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


def test_logout_closes_the_open_websocket(admin):
    """Logout of the session: its open connection gets {"status": 401} and is closed with 4401."""
    with ws_connect(admin.session.cookies["molior_session"]) as ws:
        assert json.loads(ws.recv(timeout=10)) == {"subject": 1, "event": 4}
        assert admin.get("/api/logout").status_code == 200
        assert receive_all(ws) == [{"status": 401}]
        assert ws.close_code == 4401


def test_logout_in_another_browser_closes_the_websocket(admin):
    """Logout ends all sessions of the user: the connection of another browser gets 401 too."""
    other = Api().login("admin", ADMIN_PASSWORD)
    assert other.session.cookies["molior_session"] != admin.session.cookies["molior_session"]
    with ws_connect(admin.session.cookies["molior_session"]) as ws:
        assert json.loads(ws.recv(timeout=10)) == {"subject": 1, "event": 4}
        assert other.get("/api/logout").status_code == 200
        assert receive_all(ws) == [{"status": 401}]
        assert ws.close_code == 4401


def test_deleting_a_user_closes_its_websocket(admin, unique):
    name = unique("user")
    r = admin.post("/api/users", json={"name": name, "email": f"{name}@example.com", "password": "pw-" + name})
    assert r.status_code == 200, r.text
    user = Api().login(name, "pw-" + name)
    user_id = user.get("/api/userinfo").json()["user_id"]
    with ws_connect(user.session.cookies["molior_session"]) as ws:
        assert json.loads(ws.recv(timeout=10)) == {"subject": 1, "event": 4}
        assert admin.delete(f"/api/users/{user_id}").status_code == 200
        assert receive_all(ws) == [{"status": 401}]
        assert ws.close_code == 4401
