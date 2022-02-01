import re
from aiohttp import web
from sqlalchemy import func

from ..app import app, logger
from ..auth import req_admin
from ..tools import OKResponse, ErrorResponse, db2array, escape_for_like
from ..molior.queues import enqueue_aptly

from ..molior.configuration import Configuration
from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_mirror
from ..model.mirrorkey import MirrorKey
from ..tools import paginate, array2db


@app.http_get("/api2/mirror/{name}/{version}")
@app.authenticated
async def get_mirror2(request):
    """
    Returns all mirrors with given 'name' and 'version'.

    ---
    description: Returns all mirrors with given 'name' and 'version'.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: path
          required: true
          type: string
          description: Search for mirrors with this name
        - name: version
          in: path
          required: true
          type: string
          description: Search for mirrors with this version
    produces:
        - text/json
    """
    mirror_name = request.match_info["name"]
    mirror_version = request.match_info["version"]

    query = request.cirrina.db_session.query(ProjectVersion)
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror == "true",
                         func.lower(Project.name) == mirror_name.lower(),
                         func.lower(ProjectVersion.name) == mirror_version.lower())

    mirror = query.first()
    if not mirror:
        return ErrorResponse(404, "Mirror not found")

    mirrorkeyurl = ""
    mirrorkeyids = ""
    mirrorkeyserver = ""
    mirrorkey = request.cirrina.db_session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
    if mirrorkey:
        mirrorkeyurl = mirrorkey.keyurl
        if mirrorkey.keyids:
            mirrorkeyids = mirrorkey.keyids[1:-1]
        mirrorkeyserver = mirrorkey.keyserver

    apt_url = mirror.get_apt_repo(url_only=True)
    basemirror_url = ""
    basemirror_id = -1
    basemirror_name = ""
    if not mirror.project.is_basemirror and mirror.basemirror:
        basemirror_id = mirror.basemirror.id
        basemirror_url = mirror.basemirror.get_apt_repo(url_only=True)
        basemirror_name = mirror.basemirror.project.name + "/" + mirror.basemirror.name

    result = {
        "id": mirror.id,
        "name": mirror.project.name,
        "version": mirror.name,
        "url": mirror.mirror_url,
        "basemirror_id": basemirror_id,
        "basemirror_url": basemirror_url,
        "basemirror_name": basemirror_name,
        "distribution": mirror.mirror_distribution,
        "components": mirror.mirror_components,
        "is_basemirror": mirror.project.is_basemirror,
        "architectures": db2array(mirror.mirror_architectures),
        "is_locked": mirror.is_locked,
        "with_sources": mirror.mirror_with_sources,
        "with_installer": mirror.mirror_with_installer,
        "project_id": mirror.project.id,
        "state": mirror.mirror_state,
        "apt_url": apt_url,
        "mirrorkeyurl": mirrorkeyurl,
        "mirrorkeyids": mirrorkeyids,
        "mirrorkeyserver": mirrorkeyserver,
        "external_repo": mirror.external_repo,
        "dependency_policy": mirror.dependency_policy
    }
    return web.json_response(result)


@app.http_get("/api2/mirror/{mirror_name}/{mirror_version}/dependents")
@app.authenticated
async def get_projectversion_dependents(request):
    """
    Returns a list of projectversions for the given mirror.

    ---
    description: Returns a list of projectversions for the given mirror.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: mirror_name
          in: path
          required: true
          type: string
          description: Mirror name
        - name: mirror_version
          in: path
          required: true
          type: string
          description: Mirror version
        - name: q
          in: query
          required: false
          type: string
          description: String to filter project name
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
    produces:
        - text/json
    """
    db = request.cirrina.db_session
    filter_name = request.GET.getone("q", None)

    mirror = get_mirror(request)
    if not mirror:
        return ErrorResponse(400, "Mirror not found")

    dependents = []
    nb_results = 0
    if mirror.project.is_basemirror:
        query = db.query(ProjectVersion).filter(ProjectVersion.basemirror_id == mirror.id)
        if filter_name:
            escaped_filter_name = escape_for_like(filter_name)
            query = query.filter(ProjectVersion.fullname.ilike(f"%{escaped_filter_name}%"))
        nb_results = query.count()
        query = paginate(request, query)
        dependents = query.all()

    dependents += mirror.dependents
    nb_results += len(mirror.dependents)

    results = []
    for dependent in dependents:
        results.append(dependent.data())

    data = {"total_result_count": nb_results, "results": results}
    return OKResponse(data)


@app.http_get("/api2/mirror/{name}/{version}/aptsources")
async def get_apt_sources2(request):
    """
    Returns apt sources list for given mirror.

    ---
    description: Returns apt sources list for given mirror.
    tags:
        - Mirrors
    parameters:
        - name: name
          in: path
          required: true
          type: string
          description: Mirror name
        - name: version
          in: path
          required: true
          type: string
          description: Mirror version
    produces:
        - text/json
    """
    name = request.match_info["name"]
    version = request.match_info["version"]

    db = request.cirrina.db_session
    query = db.query(ProjectVersion)
    query = query.join(Project, Project.id == ProjectVersion.project_id)
    query = query.filter(Project.is_mirror == "true",
                         func.lower(Project.name) == name.lower(),
                         func.lower(ProjectVersion.name) == version.lower())
    mirror = query.first()
    if not mirror:
        return ErrorResponse(404, "Mirror not found")

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public")
    if not apt_url:
        apt_url = cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources_list = "# APT Sources for mirror {0} {1}\n".format(name, version)
    sources_list += "# GPG-Key: {0}/{1}\n\n".format(apt_url, keyfile)
    if mirror.project.is_basemirror:
        sources_list += "{}\n".format(mirror.get_apt_repo())
    elif mirror.basemirror:
        sources_list += "{}\n".format(mirror.basemirror.get_apt_repo())
        sources_list += "{}\n".format(mirror.get_apt_repo())

    return web.Response(status=200, text=sources_list)


@app.http_post("/api2/mirror")
@req_admin
# FIXME: req_role
async def create_mirror2(request):
    """
    Create a debian mirror.

    ---
    description: Create a debian mirror.
    tags:
        - Mirrors
    parameters:
        - name: body
          in: body
          description: Mirror data
          required: true
          schema:
              type: object
              properties:
                  mirrorname:
                      required: true
                      type: string
                      description: Mirror name
                  mirrorversion:
                      required: true
                      type: string
                      description: Mirror version
                  mirrortype:
                      required: false
                      type: string
                      description: Mirror type
                  basemirror:
                      required: false
                      type: string
                      description: Base mirror name, e.g. project/version
                  external:
                      required: false
                      type: boolean
                      description: Is it an external repository?
                  mirrorurl:
                      required: false
                      type: string
                      description: Mirror URL
                  mirrordist:
                      required: false
                      type: string
                      description: Mirror distribution
                  mirrorcomponents:
                      required: true
                      type: array
                      description: Components to be mirrored
                      default: main
                  architectures:
                      required: false
                      type: array
                      items:
                          type: string
                      description: E.g. i386, amd64, arm64, armhf, ...
                      example: ["amd64", "armhf"]
                  mirrorsrc:
                      required: false
                      type: boolean
                      description: Is a mirror with sources?
                  mirrorinst:
                      required: false
                      type: boolean
                      description: Is a mirror with installer?
                  mirrorkeyserver:
                      required: false
                      type: string
                      description: Host name where the keys are
                  mirrorkeyurl:
                      required: false
                      type: string
                      description: URL of the mirror key
                  mirrorkeyids:
                      required: false
                      type: array
                      items:
                          type: string
                      description: IDs of the mirror keys
                  dependencylevel:
                      required: false
                      type: string
                      description: Dependency policy, e.g. strict
    produces:
        - text/json
    """
    params = await request.json()

    mirrorname        = params.get("mirrorname")        # noqa: E221
    mirrorversion     = params.get("mirrorversion")     # noqa: E221
    mirrortype        = params.get("mirrortype")        # noqa: E221
    basemirror        = params.get("basemirror")        # noqa: E221
    external_repo     = params.get("external")          # noqa: E221
    mirrorurl         = params.get("mirrorurl")         # noqa: E221
    mirrordist        = params.get("mirrordist")        # noqa: E221
    mirrorcomponents  = params.get("mirrorcomponents")  # noqa: E221
    architectures     = params.get("architectures")     # noqa: E221
    mirrorsrc         = params.get("mirrorsrc")         # noqa: E221
    mirrorinst        = params.get("mirrorinst")        # noqa: E221
    mirrorkeyurl      = params.get("mirrorkeyurl")      # noqa: E221
    mirrorkeyids      = params.get("mirrorkeyids")      # noqa: E221
    mirrorkeyserver   = params.get("mirrorkeyserver")   # noqa: E221
    dependency_policy = params.get("dependencylevel")   # noqa: E221
    mirrorfilter      = params.get("mirrorfilter")      # noqa: E221
    mirrorfilterwithdeps = params.get("mirrorfilterwithdeps")  # noqa: E221

    mirrorcomponents = re.split(r"[, ]", mirrorcomponents)

    db = request.cirrina.db_session
    mirror = db.query(ProjectVersion).join(Project).filter(
                func.lower(ProjectVersion.name) == mirrorversion.lower(),
                func.lower(Project.name) == mirrorname.lower()).first()
    if mirror:
        return ErrorResponse(400, "Mirror {}/{} already exists".format(mirrorname, mirrorversion))

    basemirror_id = None
    if mirrortype == "2":
        base_project, base_version = basemirror.split("/")
        query = db.query(ProjectVersion)
        query = query.join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(True))
        query = query.filter(func.lower(Project.name) == base_project.lower())
        query = query.filter(func.lower(ProjectVersion.name) == base_version.lower())
        entry = query.first()

        if not entry:
            return ErrorResponse(400, "Invalid basemirror")

        basemirror_id = entry.id

    if not mirrorcomponents:
        mirrorcomponents = ["main"]

    is_basemirror = mirrortype == "1"
    if is_basemirror:
        dependency_policy = "strict"

    if mirrorkeyurl != "":
        mirrorkeyids = []
        mirrorkeyserver = ""
    elif mirrorkeyids:
        mirrorkeyurl = ""
        mirrorkeyids = re.split(r"[, ]", mirrorkeyids)
    else:
        mirrorkeyurl = ""
        mirrorkeyids = []
        mirrorkeyserver = ""

    args = {
        "create_mirror": [
            mirrorname,
            mirrorurl,
            mirrordist,
            mirrorcomponents,
            mirrorkeyids,
            mirrorkeyserver,
            is_basemirror,
            architectures,
            mirrorversion,
            mirrorkeyurl,
            basemirror_id,
            mirrorsrc,
            mirrorinst,
            external_repo,
            dependency_policy,
            mirrorfilter,
            mirrorfilterwithdeps
        ]
    }
    await enqueue_aptly(args)
    return OKResponse("Mirror creation started")


@app.http_put("/api2/mirror/{name}/{version}")
@req_admin
# FIXME: req_role
async def edit_mirror(request):
    """
    Edit a debian mirror.

    ---
    description: Edit a debian mirror.
    tags:
        - Mirrors
    parameters:
        - name: name
          in: path
          type: string
          required: true
          description: Mirror name
        - name: version
          in: path
          type: string
          required: true
          description: Mirror version
        - name: body
          in: body
          description: Mirror data
          required: true
          schema:
              type: object
              properties:
                  mirrortype:
                      required: true
                      type: string
                      description: Mirror type
                  basemirror:
                      required: false
                      type: string
                      description: Base mirror name, e.g. project/version
                  mirrorurl:
                      required: true
                      type: string
                      description: Mirror URL
                  mirrordist:
                      required: true
                      type: string
                      description: Mirror distribution
                  mirrorcomponents:
                      required: true
                      type: array
                      description: Components to be mirrored
                      default: main
                  architectures:
                      required: true
                      type: array
                      items:
                          type: string
                      description: E.g. i386, amd64, arm64, armhf, ...
                      example: ["amd64", "armhf"]
                  mirrorsrc:
                      required: false
                      type: boolean
                      description: Is a mirror with sources?
                  mirrorinst:
                      required: false
                      type: boolean
                      description: Is a mirror with installer?
                  mirrorkeyserver:
                      required: false
                      type: string
                      description: Host name where the keys are
                  mirrorkeyurl:
                      required: false
                      type: string
                      description: URL of the mirror key
                  mirrorkeyids:
                      required: false
                      type: array
                      items:
                          type: string
                      description: IDs of the mirror keys
                  dependencylevel:
                      required: false
                      type: string
                      description: Dependency policy
                      example: strict
    """
    db = request.cirrina.db_session
    mirror_name = request.match_info["name"]
    mirror_version = request.match_info["version"]
    params = await request.json()

    mirror = db.query(ProjectVersion).join(Project).filter(
                ProjectVersion.project_id == Project.id,
                func.lower(ProjectVersion.name) == mirror_version.lower(),
                func.lower(Project.name) == mirror_name.lower()).first()
    if not mirror:
        return ErrorResponse(400, "Mirror not found {}/{}".format(mirror_name, mirror_version))

    mirrorkey = db.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
    if not mirrorkey:
        return ErrorResponse(400, "Mirror keys not found for mirror {}".format(mirror.id))

    if mirror.is_locked:
        return ErrorResponse(400, "Mirror is locked")

    mirrortype        = params.get("mirrortype")        # noqa: E221
    basemirror        = params.get("basemirror")        # noqa: E221
    mirrorurl         = params.get("mirrorurl")         # noqa: E221
    mirrordist        = params.get("mirrordist")        # noqa: E221
    mirrorcomponents  = params.get("mirrorcomponents")  # noqa: E221
    architectures     = params.get("architectures")     # noqa: E221
    mirrorsrc         = params.get("mirrorsrc")         # noqa: E221
    mirrorinst        = params.get("mirrorinst")        # noqa: E221
    mirrorkeyurl      = params.get("mirrorkeyurl")      # noqa: E221
    mirrorkeyids      = params.get("mirrorkeyids")      # noqa: E221
    mirrorkeyserver   = params.get("mirrorkeyserver")   # noqa: E221
    dependency_policy = params.get("dependencylevel")   # noqa: E221
    mirrorfilter      = params.get("mirrorfilter")      # noqa: E221
    mirrorfilterwithdeps = params.get("mirrorfilterwithdeps")  # noqa: E221

    if basemirror:
        basemirror_name, basemirror_version = basemirror.split("/")
        bm = db.query(ProjectVersion).join(Project).filter(
                    func.lower(Project.name) == basemirror_name.lower(),
                    func.lower(ProjectVersion.name) == basemirror_version.lower()).first()
        if not bm:
            return ErrorResponse(400, "Error finding basemirror '%s'", basemirror)
        mirror.basemirror = bm

    mirror.mirror_url = mirrorurl
    mirror.mirror_distribution = mirrordist
    mirror.mirror_components = mirrorcomponents
    mirror.mirror_architectures = "{" + ", ".join(architectures) + "}"
    mirror.mirror_with_sources = mirrorsrc
    mirror.mirror_with_installer = mirrorinst
    mirror.is_basemirror = mirrortype == "1"
    mirror.mirror_filter = mirrorfilter
    mirror.mirror_filter_with_deps = mirrorfilterwithdeps

    if mirrortype == "2":
        mirror.dependency_policy = dependency_policy

    if mirrorkeyurl != "":
        mirrorkeyids = []
        mirrorkeyserver = ""
    elif mirrorkeyids:
        mirrorkeyurl = ""
        mirrorkeyids = re.split(r"[, ]", mirrorkeyids)
    else:
        mirrorkeyurl = ""
        mirrorkeyids = []
        mirrorkeyserver = ""

    mirrorkey.keyurl = mirrorkeyurl
    mirrorkey.keyids = array2db(mirrorkeyids)
    mirrorkey.keyserver = mirrorkeyserver

    db.commit()

    if mirror.mirror_state == "init_error":
        args = {"init_mirror": [mirror.id]}
    else:
        args = {"update_mirror": [mirror.id]}
    await enqueue_aptly(args)
    return OKResponse("Mirror update started")


@app.http_delete("/api2/mirror/{name}/{version}")
@req_admin
# FIXME: req_role
async def delete_mirror2(request):
    """
    Delete a single mirror on aptly and from database.

    ---
    description: Delete a single mirror on aptly and from database.
    tags:
        - Mirrors
    parameters:
        - name: name
          in: path
          required: true
          type: string
          description: Mirror name
        - name: version
          in: path
          type: string
          required: true
          description: Mirror version
    produces:
        - text/json
    """
    db = request.cirrina.db_session
    mirror_name = request.match_info["name"]
    mirror_version = request.match_info["version"]

    mirror = db.query(ProjectVersion).join(Project).filter(
                ProjectVersion.project_id == Project.id,
                func.lower(ProjectVersion.name) == mirror_version.lower(),
                func.lower(Project.name) == mirror_name.lower(),
                Project.is_mirror.is_(True)).first()
    if not mirror:
        return ErrorResponse(400, "Mirror not found {}/{}".format(mirror_name, mirror_version))

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
        logger.warning("error deleting mirror '%s': referenced by one or more project versions", mirrorname)
        return ErrorResponse(412, "Error deleting mirror {}: still referenced from project versions".format(mirrorname))

    if mirror.project.is_basemirror:
        dependents = db.query(ProjectVersion).filter(ProjectVersion.basemirror_id == mirror.id).all()
        if dependents:
            logger.warning("error deleting mirror '%s': used as basemirror by one or more project versions", mirrorname)
            return ErrorResponse(412,
                                 "Error deleting mirror {}: still used as base mirror by one or more project versions".format(
                                     mirrorname))

    mirror.is_deleted = True
    db.commit()
    args = {"delete_mirror": [mirror.id]}
    await enqueue_aptly(args)

    return OKResponse("Successfully deleted mirror: {}".format(mirrorname))
