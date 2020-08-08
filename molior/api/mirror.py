from aiohttp import web
from sqlalchemy.sql import or_

from ..app import app, logger
from ..auth import req_admin
from ..tools import OKResponse, ErrorResponse, paginate

from ..model.project import Project
from ..model.projectversion import ProjectVersion
from ..model.mirrorkey import MirrorKey


@app.http_post("/api/mirror")
@req_admin
# FIXME: req_role
async def create_mirror(request):
    """
    Create a debian aptly mirror.

    ---
    description: Create a debian aptly mirror.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: true
          type: string
          description: name of the mirror
        - name: url
          in: query
          required: true
          type: string
          description: http://host of source
        - name: distribution
          in: query
          required: true
          type: string
          description: trusty, wheezy, jessie, etc.
        - name: components
          in: query
          required: false
          type: array
          description: components to be mirrored
          default: main
        - name: keys
          in: query
          required: false
          type: array
          uniqueItems: true
          collectionFormat: multi
          allowEmptyValue: true
          minItems: 0
          items:
              type: string
          description: repository keys
        - name: keyserver
          in: query
          required: false
          type: string
          description: host name where the keys are
        - name: is_basemirror
          in: query
          required: false
          type: boolean
          description: use this mirror for chroot
        - name: architectures
          in: query
          required: false
          type: array
          description: i386,amd64,arm64,armhf,...
        - name: version
          in: query
          required: false
          type: string
        - name: armored_key_url
          in: query
          required: false
          type: string
        - name: basemirror_id
          in: query
          required: false
          type: string
        - name: download_sources
          in: query
          required: false
          type: boolean
        - name: download_installer
          in: query
          required: false
          type: boolean
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: mirror creation failed.
        "412":
            description: key error.
        "409":
            description: mirror already exists.
        "500":
            description: internal server error.
        "503":
            description: aptly not available.
        "501":
            description: database error occurred.
    """
    params = await request.json()

    mirror = params.get("name")
    url = params.get("url")
    mirror_distribution = params.get("distribution")
    components = params.get("components", [])
    keys = params.get("keys", [])
    keyserver = params.get("keyserver")
    is_basemirror = params.get("is_basemirror")
    architectures = params.get("architectures", [])
    version = params.get("version")
    key_url = params.get("armored_key_url")
    basemirror_id = params.get("basemirror_id")
    download_sources = params.get("download_sources")
    download_installer = params.get("download_installer")

    if not components:
        components = ["main"]

    if not isinstance(is_basemirror, bool):
        return ErrorResponse("is_basemirror not a bool")

    args = {
        "create_mirror": [
            mirror,
            url,
            mirror_distribution,
            components,
            keys,
            keyserver,
            is_basemirror,
            architectures,
            version,
            key_url,
            basemirror_id,
            download_sources,
            download_installer,
        ]
    }
    await request.cirrina.aptly_queue.put(args)
    return OKResponse("Mirror {} successfully created.".format(mirror))


@app.http_get("/api/mirror")
@app.http_get("/api/mirrors")
@app.authenticated
async def get_mirrors(request):
    """
    Returns all mirrors from database.

    ---
    description: Returns mirrors from database.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: page
          in: query
          required: false
          type: integer
          default: 1
          description: page number
        - name: page_size
          in: query
          required: false
          type: integer
          default: 10
          description: max. mirrors per page
        - name: q
          in: query
          required: false
          type: string
          description: filter criteria
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: bad request
    """
    search = request.GET.getone("q", "")
    basemirror = request.GET.getone("basemirror", False)
    is_basemirror = request.GET.getone("is_basemirror", False)
    url = request.GET.getone("url", "")

    query = request.cirrina.db_session.query(ProjectVersion).join(Project)
    query = query.filter(Project.is_mirror == "true")

    if search:
        query = query.filter(or_(Project.name.like("%{}%".format(search)), ProjectVersion.name.like("%{}%".format(search))))

    if url:
        query = query.filter(ProjectVersion.mirror_url.like("%{}%".format(url)))

    if basemirror:
        query = query.filter(Project.is_basemirror == "true", ProjectVersion.mirror_state == "ready")
    elif is_basemirror:
        query = query.filter(Project.is_basemirror == "true")

    query = query.order_by(Project.name, ProjectVersion.name.desc())
    nb_results = query.count()

    query = paginate(request, query)
    results = query.all()
    data = {"total_result_count": nb_results, "results": []}

    for mirror in results:
        apt_url = mirror.get_apt_repo(url_only=True)
        base_mirror_url = ""
        base_mirror_id = -1
        base_mirror_name = ""
        mirrorkeyurl = ""
        mirrorkeyids = ""
        mirrorkeyserver = ""

        if not mirror.project.is_basemirror and mirror.basemirror:
            base_mirror_id = mirror.basemirror.id
            base_mirror_url = mirror.basemirror.get_apt_repo(url_only=True)
            base_mirror_name = "{}/{}".format(mirror.basemirror.project.name, mirror.basemirror.name)
            mirrorkey = request.cirrina.db_session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
            if mirrorkey:
                mirrorkeyurl = mirrorkey.keyurl
                mirrorkeyids = mirrorkey.keyids[1:-1]
                mirrorkeyserver = mirrorkey.keyserver

        data["results"].append(
            {
                "id": mirror.id,
                "name": mirror.project.name,
                "version": mirror.name,
                "url": mirror.mirror_url,
                "basemirror_id": base_mirror_id,
                "basemirror_url": base_mirror_url,
                "basemirror_name": base_mirror_name,
                "distribution": mirror.mirror_distribution,
                "components": mirror.mirror_components,
                "is_basemirror": mirror.project.is_basemirror,
                "architectures": mirror.mirror_architectures[1:-1].split(","),
                "is_locked": mirror.is_locked,
                "with_sources": mirror.mirror_with_sources,
                "with_installer": mirror.mirror_with_installer,
                "project_id": mirror.project.id,
                "state": mirror.mirror_state,
                "apt_url": apt_url,
                "mirrorkeyurl": mirrorkeyurl,
                "mirrorkeyids": mirrorkeyids,
                "mirrorkeyserver": mirrorkeyserver
            }
        )
    return web.json_response(data)


@app.http_get("/api/mirror/{name}/{version}")
@app.authenticated
async def get_mirror(request):
    """
    Returns all mirrors from database.

    ---
    description: Returns mirrors from database.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: false
          type: string
          description: filter criteria
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: bad request
    """
    mirror_name = request.match_info["name"]
    mirror_version = request.match_info["version"]

    query = request.cirrina.db_session.query(ProjectVersion)
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror == "true",
                         Project.name == mirror_name,
                         ProjectVersion.name == mirror_version)

    mirror = query.first()

    if not mirror:
        return ErrorResponse(404, "Mirror not found")

    apt_url = mirror.get_apt_repo(url_only=True)
    basemirror_url = ""
    basemirror_name = ""
    if not mirror.project.is_basemirror and mirror.basemirror:
        basemirror_url = mirror.basemirror.get_apt_repo(url_only=True)
        basemirror_name = mirror.basemirror.project.name + "/" + mirror.basemirror.name

    result = {
        "id": mirror.id,
        "name": mirror.project.name,
        "version": mirror.name,
        "url": mirror.mirror_url,
        "basemirror_url": basemirror_url,
        "basemirror_name": basemirror_name,
        "distribution": mirror.mirror_distribution,
        "components": mirror.mirror_components,
        "is_basemirror": mirror.project.is_basemirror,
        "architectures": mirror.mirror_architectures[1:-1],
        "is_locked": mirror.is_locked,
        "with_sources": mirror.mirror_with_sources,
        "with_installer": mirror.mirror_with_installer,
        "project_id": mirror.project.id,
        "state": mirror.mirror_state,
        "apt_url": apt_url,
    }
    return web.json_response(result)


@app.http_delete("/api/mirror/{id}")
@req_admin
# FIXME: req_role
async def delete_mirror(request):
    """
    Delete a single mirror on aptly and from database.

    ---
    description: Delete a single mirror on aptly and from database.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: id
          in: path
          required: true
          type: integer
          description: id of the mirror
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: removal failed from aptly.
        "404":
            description: mirror not found on aptly.
        "500":
            description: internal server error.
        "503":
            description: removal failed from database.
    """
    mirror_id = request.match_info["id"]

    query = request.cirrina.db_session.query(ProjectVersion)
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror.is_(True))
    mirror = query.filter(ProjectVersion.id == mirror_id).first()

    if not mirror:
        logger.warning("error deleting mirror '%s': mirror not found", mirror_id)
        return ErrorResponse(404, "Error deleting mirror '%d': mirror not found" % mirror_id)

    # FIXME: check state, do not delete ready/updating/...

    mirrorname = "{}-{}".format(mirror.project.name, mirror.name)

    # check relations
    if mirror.sourcerepositories:
        logger.warning("error deleting mirror '%s': referenced by one or more source repositories", mirrorname)
        return ErrorResponse(412, "Error deleting mirror {}: still referenced from source repositories".format(mirrorname))
    # FIXME: how to check build references
    # if mirror.buildconfiguration:
    #    logger.warning("error deleting mirror '%s': referenced by one or more build configurations", mirrorname)
    #    return ErrorResponse(412, "Error deleting mirror {}: still referenced from build configurations".format(mirrorname))
    if mirror.dependents:
        logger.warning("error deleting mirror '%s': referenced by one or project versions", mirrorname)
        return ErrorResponse(412, "Error deleting mirror {}: still referenced from project versions".format(mirrorname))

    args = {"delete_mirror": [mirror.id]}
    await request.cirrina.aptly_queue.put(args)

    return OKResponse("Successfully deleted mirror: {}".format(mirrorname))


@app.http_post("/api/mirror/{id}/update")
@app.http_put("/api/mirror/{id}")
@req_admin
# FIXME: req_role
async def put_update_mirror(request):
    """
    Updates a mirror.

    ---
    description: Updates a mirror.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: path
          required: true
          type: integer
          description: name of the mirror
    produces:
        - text/json
    responses:
        "200":
            description: Mirror update successfully started.
        "400":
            description: Mirror not in error state.
        "500":
            description: Internal server error.
    """
    mirror_id = request.match_info["id"]
    mirror = request.cirrina.db_session.query(ProjectVersion).filter(ProjectVersion.id == mirror_id).first()

    if mirror.is_locked:
        return ErrorResponse(400, "Mirror is locked")

    if (mirror.mirror_state != "error" and mirror.mirror_state != "init_error" and mirror.mirror_state != "new"):
        return ErrorResponse(400, "Mirror not in error state")

    if mirror.mirror_state == "new":
        args = {"init_mirror": [mirror.id]}
    else:
        args = {"update_mirror": [mirror.id]}
    await request.cirrina.aptly_queue.put(args)

    return OKResponse("Successfully started update on mirror")
