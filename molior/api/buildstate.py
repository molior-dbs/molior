"""
Provides functions to interact with the BuildState
database model.
"""
from aiohttp import web

from molior.model.build import BUILD_STATES

from .app import app


@app.http_get("/api/buildstates")
@app.authenticated
async def get_buildstates(*_):
    """
    Returns a list of all buildstates.

    ---
    description: Returns a list of buildstates.
    tags:
        - BuildStates
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    data = {"total_result_count": len(BUILD_STATES), "results": BUILD_STATES}
    return web.json_response(data)
