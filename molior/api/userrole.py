from aiohttp import web

from ..app import app
from ..model.userrole import USER_ROLES


@app.http_get("/api/userroles")
async def get_userroles(*_):
    """
    ---
    description: Return the list of user role enumerator
    tags:
    - Project UserRole
    produces:
    - application/json
    responses:
        "200":
            description: Return an array with results
    """
    return web.json_response(USER_ROLES)
