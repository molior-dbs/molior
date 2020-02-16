import logging

from aiohttp import web

from molior.app import app
from molior.model.userrole import USER_ROLES

logger = logging.getLogger("molior")


@app.http_get("/api/userroles")
async def get_userroles(*_):
    """
    ---
    description: Return the list of user role enumerator
    tags:
    - Project UserRole
    produces:
    - application/json
    responsses:
        "200":
            description: Return an array with results
    """
    return web.json_response(USER_ROLES)
