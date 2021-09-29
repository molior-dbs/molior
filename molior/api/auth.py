from aiohttp import web

from ..app import app
from ..model.user import User


@app.http_get("/api/userinfo")
@app.authenticated
async def get_userinfo(request):
    username = request.cirrina.web_session.get("username")
    if username:
        user = request.cirrina.db_session.query(User).filter_by(username=username.lower()).first()
        if user:
            return web.json_response({"username": username, "user_id": user.id, "is_admin": user.is_admin})
    return web.json_response({"username": username, "user_id": -1, "is_admin": False})
