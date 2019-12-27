"""
Provides functions to check the current status
of the molior packages and their version
"""

from aiohttp import web

from .app import app
from molior.version import MOLIOR_VERSION
from molior.molior.backend import Backend


@app.http_get("/api/status")
async def get_status(request):
    """
    Returns a dictionary, which includes status of each molior package and
    the version

    ---
    description: Returns a dictionary, which includes status of each molior package and the version
    tags:
        - Status
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    maintenance_message = ""
    maintenance_mode = False

    query = "select value from metadata where name = :key"
    result = request.cirrina.db_session.execute(query, {"key": "maintenance_mode"})
    for value in result:
        if value[0] == "true":
            maintenance_mode = True
        break

    result = request.cirrina.db_session.execute(query, {"key": "maintenance_message"})
    for value in result:
        maintenance_message = value[0]
        break

    status = {
        "versions": {"molior-server": [MOLIOR_VERSION]},
        "maintenance_message": maintenance_message,
        "maintenance_mode": maintenance_mode,
    }
    return web.json_response(status)


@app.http_post("/api/status/maintenance")
@app.req_admin
async def set_maintenance(request):
    """
    Set maintenance mode and message

    ---
    description: Adds given sourcerepositories to given projectversion.
    tags:
        - Maintenance
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: maintenance_mode
          in: query
          required: false
          type: boolean
          description: enable/disable maintenance mode
          examples: ["true", "false"]
        - name: maintenance_message
          in: query
          required: false
          type: string
          description: maintenance message
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
    """
    params = await request.json()

    status = {}

    maintenance_mode = params.get("maintenance_mode")
    if maintenance_mode != "":
        maintenance_mode = "true" if maintenance_mode == "false" else "false"
        query = "update metadata set value = :maintenance_mode where name = :key"
        request.cirrina.db_session.execute(
            query, {"key": "maintenance_mode", "maintenance_mode": maintenance_mode}
        )
        status.update(
            {"maintenance_mode": True if maintenance_mode == "true" else False}
        )

    maintenance_message = params.get("maintenance_message")
    if maintenance_message != "":
        query = "update metadata set value = :maintenance_message where name = :key"
        request.cirrina.db_session.execute(
            query,
            {"key": "maintenance_message", "maintenance_message": maintenance_message},
        )
        status.update({"maintenance_message": maintenance_message})

    return web.json_response(status)


@app.http_get("/api/nodes")
async def get_nodes_info(request):
    """
    Returns info about the build nodes

    ---
    description: Returns info about the build nodes
    tags:
        - Status
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    search = request.GET.getone("q", None)
    page = int(request.GET.getone("page", 1))
    page_size = int(request.GET.getone("page_size", 10))

    b = Backend()
    backend = b.get_backend()
    build_nodes = backend.get_nodes_info()
    # uptime_string = str(timedelta(seconds = uptime_seconds))

    results = []
    for name in build_nodes:  # FIXME: sort?
        if search and search not in name:
            continue

        load = ""
        for l in build_nodes[name]["load"]:
            if load:
                load += ", "
            load += str(l)
        build_nodes[name]["load"] = load
        results.append({**build_nodes[name], **{"name": name}})

    result_page = results[page_size * (page - 1):page_size*page]
    data = {"total_result_count": len(results), "results": result_page}
    return web.json_response(data)
