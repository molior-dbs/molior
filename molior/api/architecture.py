from aiohttp import web

from molior.app import app
from molior.model.architecture import Architecture


@app.http_get("/api/architectures")
@app.authenticated
async def get_architectures(request):
    """
    Gets a list of all architectures from
    the database.

    ---
    description: Returns a list of architectures
    tags:
        - Architectures
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    query = request.cirrina.db_session.query(Architecture)
    data = {"total_result_count": query.count(), "results": []}

    # FIXME: remove all from database
    for architecture in query.filter(Architecture.name != "all").all():
        data["results"].append({"id": architecture.id, "name": architecture.name})
    return web.json_response(data)
