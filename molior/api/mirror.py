from aiohttp import web

from molior.app import app, logger
from molior.auth import req_admin
from molior.model.build import Build
from molior.model.chroot import Chroot
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion
from molior.model.buildvariant import BuildVariant
from molior.tools import get_aptly_connection, paginate


def error(status, msg, *args):
    """
    Logs an error message and returns an error to
    the web client.

    Args:
        status (int): The http response status.
        msg (str): The message to display.
        args (tuple): Arguments for string format on msg.
    """
    logger.error(msg.format(*args))
    return web.Response(status=status, text=msg.format(*args))


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
        return web.Response(status=400, text="is_basemirror not a bool")

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
    return web.Response(status=200, text="Mirror {} successfully created.".format(mirror))


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
    filter_name = request.GET.getone("q", "")
    basemirror = request.GET.getone("basemirror", False)
    is_basemirror = request.GET.getone("is_basemirror", False)

    query = request.cirrina.db_session.query(ProjectVersion)
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror == "true")

    if filter_name:
        query = query.filter(Project.name.like("%{}%".format(filter_name)))

    if basemirror:
        query = query.filter(Project.is_basemirror == "true", ProjectVersion.mirror_state == "ready")
    elif is_basemirror:
        query = query.filter(Project.is_basemirror == "true")

    query = query.order_by(Project.name, ProjectVersion.name)
    nb_results = query.count()

    query = paginate(request, query)
    results = query.all()
    data = {"total_result_count": nb_results, "results": []}

    for mirror in results:
        apt_url = mirror.get_apt_repo(url_only=True)
        base_mirror_url = str()
        if not mirror.project.is_basemirror and mirror.buildvariants:
            # FIXME: only one buildvariant supported
            base_mirror = mirror.buildvariants[0].base_mirror
            base_mirror_url = base_mirror.get_apt_repo(url_only=True)

        data["results"].append(
            {
                "id": mirror.id,
                "name": mirror.project.name,
                "version": mirror.name,
                "url": mirror.mirror_url,
                "base_mirror": base_mirror_url,
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
        return web.Response(text="Mirror not found", status=404)

    apt_url = mirror.get_apt_repo(url_only=True)
    base_mirror_url = str()
    if not mirror.project.is_basemirror and mirror.buildvariants:
        # FIXME: only one buildvariant supported
        base_mirror = mirror.buildvariants[0].base_mirror
        base_mirror_url = base_mirror.get_apt_repo(url_only=True)

    result = {
        "id": mirror.id,
        "name": mirror.project.name,
        "version": mirror.name,
        "url": mirror.mirror_url,
        "base_mirror": base_mirror_url,
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
    apt = get_aptly_connection()
    mirror_id = request.match_info["id"]

    query = request.cirrina.db_session.query(ProjectVersion)  # pylint: disable=no-member
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror.is_(True))
    entry = query.filter(ProjectVersion.id == mirror_id).first()

    if not entry:
        logger.warning("error deleting mirror '%s': mirror not found", mirror_id)
        return error(404, "Error deleting mirror '%d': mirror not found", mirror_id)

    # FIXME: check state, do not delete ready/updating/...

    mirrorname = "{}-{}".format(entry.project.name, entry.name)

    # check relations
    if entry.sourcerepositories:
        logger.warning("error deleting mirror '%s': referenced by one or more source repositories", mirrorname)
        return error(412, "Error deleting mirror {}: still referenced by one or more source repositories", mirrorname)
    if entry.buildconfiguration:
        logger.warning("error deleting mirror '%s': referenced by one or more build configurations", mirrorname)
        return error(412, "Error deleting mirror {}: still referenced by one or more build configurations", mirrorname)
    if entry.dependents:
        logger.warning("error deleting mirror '%s': referenced by one or project versions", mirrorname)
        return error(412, "Error deleting mirror {}: still referenced by one or more project versions", mirrorname)

    base_mirror = ""
    base_mirror_version = ""
    if not entry.project.is_basemirror:
        basemirror = entry.buildvariants[0].base_mirror
        base_mirror = basemirror.project.name
        base_mirror_version = basemirror.name
        # FIXME: cleanup chroot table, schroots, debootstrap,

    try:
        # FIXME: use altpy queue !
        await apt.mirror_delete(base_mirror, base_mirror_version, entry.project.name, entry.name, entry.mirror_distribution)
    except Exception as exc:
        # mirror did not exist
        # FIXME: handle mirror has snapshots and cannot be deleted?
        logger.exception(exc)
        pass

    project = entry.project

    bvs = request.cirrina.db_session.query(BuildVariant).filter(BuildVariant.base_mirror_id == entry.id).all()
    for bvariant in bvs:
        # FIXME: delete buildconfigurations
        if entry.project.is_basemirror:
            chroot = request.cirrina.db_session.query(Chroot).filter(Chroot.buildvariant == bvariant).first()
            if chroot:
                request.cirrina.db_session.delete(chroot)
        request.cirrina.db_session.delete(bvariant)

    builds = request.cirrina.db_session.query(Build) .filter(Build.projectversion_id == entry.id).all()
    for build in builds:
        # FIXME: delete buildconfigurations
        # FIXME: remove buildout dir
        request.cirrina.db_session.delete(build)

    request.cirrina.db_session.delete(entry)
    request.cirrina.db_session.commit()

    if not project.projectversions:
        request.cirrina.db_session.delete(project)  # pylint: disable=no-member

    request.cirrina.db_session.commit()  # pylint: disable=no-member

    return web.Response(status=200, text="Successfully deleted mirror: {}".format(mirrorname))


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
    project_v = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == mirror_id)  # pylint: disable=no-member
        .first()
    )

    if project_v.is_locked:
        return error(400, "Mirror locked. Update not allowed.")

    if project_v.mirror_state != "error":
        return error(400, "Mirror not in error state.")

    components = project_v.mirror_components.split(",")

    # FIXME: only one build variant supported
    base_mirror = None
    base_mirror_version = None
    if not project_v.project.is_basemirror:
        base_mirror = project_v.buildvariants[0].base_mirror.project.name
        base_mirror_version = project_v.buildvariants[0].base_mirror.name

    build = (
        request.cirrina.db_session.query(Build)
        .filter(Build.buildtype == "mirror", Build.projectversion_id == project_v.id)
        .first()
    )

    if not build:
        logger.error("update mirror: no build found for mirror %d", mirror_id)
        return error(400, "no build found for mirror")

    args = {
        "update_mirror": [
            build.id,
            project_v.id,
            base_mirror,
            base_mirror_version,
            project_v.project.name,
            project_v.name,
            components,
        ]
    }
    await request.cirrina.aptly_queue.put(args)

    return web.Response(status=200, text="Successfully started update on mirror")
