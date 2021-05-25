from aiohttp import web
from os.path import expanduser

from ..app import app
from ..auth import req_admin
from ..version import MOLIOR_VERSION
from ..molior.backend import Backend
from ..molior.configuration import Configuration


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

    sshkey_file = expanduser("~/.ssh/id_rsa.pub")
    sshkey = ""
    try:
        with open(sshkey_file) as f:
            sshkey = f.read()
    except Exception:
        pass

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public")
    if not apt_url:
        apt_url = cfg.aptly.get("apt_url")
    gpgurl = apt_url + "/" + cfg.aptly.get("key")
    status = {
        "version": MOLIOR_VERSION,
        "maintenance_message": maintenance_message,
        "maintenance_mode": maintenance_mode,
        "sshkey": sshkey,
        "gpgurl": gpgurl
    }
    return web.json_response(status)


@app.http_post("/api/status/maintenance")
@req_admin
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

    results = []
    for node in build_nodes:
        if search and search.lower() not in node["name"].lower():
            continue
        results.append(node)

    def sortBy(node):
        return node["name"]
    results.sort(key=sortBy)

    # FIXME: sort?

    # paginate
    result_page = results[page_size * (page - 1):page_size*page]

    data = {"total_result_count": len(results), "results": result_page}
    return web.json_response(data)


@app.http_get("/api/node/{machineID}")
async def get_node(request):
    """
    Returns info about the build node

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
    machine_id = request.match_info["machineID"]
    b = Backend()
    backend = b.get_backend()
    build_nodes = backend.get_nodes_info()
    for node in build_nodes:
        if machine_id == node["id"]:
            return web.json_response(node)
    return web.Response(text="Node not found", status=404)


@app.http_get("/api/server")
async def get_ServerInfo(request):
    """
    Returns info about the molior server

    ---
    description: Returns info about the molior server
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
    b = Backend()
    backend = b.get_backend()
    server_info = backend.get_server_info()
    if server_info:
        return web.json_response(server_info)
    return web.Response(text="Internal server error", status=500)
