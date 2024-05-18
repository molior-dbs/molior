import re

from aiohttp import web
from sqlalchemy.sql import or_
from sqlalchemy import func

from ..app import app
from ..auth import req_admin
from ..tools import OKResponse, ErrorResponse, paginate, db2array, escape_for_like
from ..molior.queues import enqueue_aptly

from ..model.project import Project
from ..model.projectversion import ProjectVersion
from ..model.mirrorkey import MirrorKey


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
    basemirror = request.GET.getone("basemirror", False)         # True returns mirrors usable for a base mirror
    is_basemirror = request.GET.getone("is_basemirror", False)   # True returns all base mirror entries
    search_basemirror = request.GET.getone("q_basemirror", "")   # Return mirrors based on search_basemirror
    url = request.GET.getone("url", "")

    query = request.cirrina.db_session.query(ProjectVersion).join(Project)
    query = query.filter(Project.is_mirror == "true", ProjectVersion.is_deleted.is_(False))

    if search:
        terms = re.split("[/ ]", search)
        for term in terms:
            if not term:
                continue
            term = escape_for_like(term)
            query = query.filter(or_(
                 Project.name.ilike("%{}%".format(term)),
                 ProjectVersion.name.ilike("%{}%".format(term))))

    basemirror_ids = []
    if search_basemirror:
        query2 = request.cirrina.db_session.query(ProjectVersion).join(Project)
        query2 = query2.filter(Project.is_basemirror == "true", ProjectVersion.is_deleted.is_(False))
        terms = re.split("[/ ]", search_basemirror)
        for term in terms:
            if not term:
                continue
            query2 = query2.filter(or_(
                 Project.name.ilike("%{}%".format(term)),
                 ProjectVersion.name.ilike("%{}%".format(term))))
        basemirrors = query2.all()
        for b in basemirrors:
            if b.id not in basemirror_ids:
                basemirror_ids.append(b.id)

        query = query.filter(ProjectVersion.basemirror_id.in_(basemirror_ids))

    if url:
        query = query.filter(ProjectVersion.mirror_url.ilike("%{}%".format(url)))

    if basemirror:
        query = query.filter(Project.is_basemirror == "true", ProjectVersion.mirror_state == "ready")
    elif is_basemirror:
        query = query.filter(Project.is_basemirror == "true")

    query = query.order_by(func.lower(Project.name), func.lower(ProjectVersion.name).desc())
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
        mirrorkey = request.cirrina.db_session.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
        if mirrorkey:
            mirrorkeyurl = mirrorkey.keyurl
            if mirrorkey.keyids:
                mirrorkeyids = db2array(mirrorkey.keyids)
            mirrorkeyserver = mirrorkey.keyserver
        if not mirror.project.is_basemirror and mirror.basemirror:
            base_mirror_id = mirror.basemirror.id
            base_mirror_url = mirror.basemirror.get_apt_repo(url_only=True)
            base_mirror_name = "{}/{}".format(mirror.basemirror.project.name, mirror.basemirror.name)

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
                "architectures": db2array(mirror.mirror_architectures),
                "is_locked": mirror.is_locked,
                "with_sources": mirror.mirror_with_sources,
                "with_installer": mirror.mirror_with_installer,
                "project_id": mirror.project.id,
                "state": mirror.mirror_state,
                "apt_url": apt_url,
                "mirrorkeyurl": mirrorkeyurl,
                "mirrorkeyids": " ".join(mirrorkeyids),
                "mirrorkeyserver": mirrorkeyserver,
                "external_repo": mirror.external_repo,
                "dependency_policy": mirror.dependency_policy,
                "mirrorfilter": mirror.mirror_filter,
            }
        )
    return web.json_response(data)


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
        - name: id
          in: path
          required: true
          type: integer
          description: id of the mirror
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

    if mirror.mirror_state == "new" or mirror.mirror_state == "init_error":
        args = {"init_mirror": [mirror.id]}
    else:
        args = {"update_mirror": [mirror.id]}
    await enqueue_aptly(args)

    return OKResponse("Successfully started update on mirror")
