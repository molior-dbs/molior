"""
/api/websocket  — general-purpose push channel
Replaces molior/api/websocket.py

Two directions:
  Server → Client: entity change events (userrole changed/removed, etc.)
  Client → Server: build log streaming requests
      {"subject": "buildlog", "action": "start", "data": {"build_id": N}}

The NotificationWorker calls app.state.broadcast(event) to fan out to all
connected clients.  This module wires that up via a simple in-memory
connection registry.
"""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...auth import decode_session_cookie

router = APIRouter(tags=["websocket"])

# In-process set of active WebSocket connections — used by NotificationWorker
_connections: set[WebSocket] = set()


async def broadcast(message: dict):
    """Broadcast a message to all connected WebSocket clients."""
    data = json.dumps(message)
    dead = set()
    for ws in _connections:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


@router.websocket("/api/websocket")
async def websocket_endpoint(websocket: WebSocket):
    # Validate session cookie before accepting
    cookies = websocket.cookies
    session_cookie = cookies.get("MOLIOR_SESSION")
    if not session_cookie or not decode_session_cookie(session_cookie):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    _connections.add(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            subject = msg.get("subject")
            action = msg.get("action")
            data = msg.get("data", {})

            if subject == "buildlog" and action == "start":
                build_id = data.get("build_id")
                if build_id:
                    # TODO: stream existing log lines then tail live log queue
                    pass

    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(websocket)
