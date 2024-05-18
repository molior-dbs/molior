import re

from sqlalchemy.sql import func, or_

from ..app import app
from ..logger import logger
from ..auth import req_role
from ..tools import ErrorResponse, parse_int, is_name_valid, OKResponse, db2array, escape_for_like
from ..model.projectversion import ProjectVersion, get_projectversion_deps
from ..model.project import Project
from ..molior.queues import enqueue_aptly


@app.http_get("/api/projectversions")
@app.authenticated
async def get_projectversions(request):
    """
    Returns a list of projectversions.

    ---
    description: Returns a list of projectversions.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: exclude_id
          in: query
          required: false
          type: integer
        - name: basemirror_id
          in: query
          required: false
          type: integer
        - name: is_basemirror
          in: query
          required: false
          type: boolean
        - name: project_id
          in: query
          required: false
          type: integer
        - name: project_name
          in: query
          required: false
          type: string
        - name: dependant_id
          in: query
          required: false
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    project_id = request.GET.getone("project_id", None)
    project_name = request.GET.getone("project_name", None)
    exclude_id = request.GET.getone("exclude_id", None)
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    dependant_id = request.GET.getone("dependant_id", None)
    search = request.GET.getone("q", "")

    query = db.query(ProjectVersion).join(Project).filter(ProjectVersion.is_deleted.is_(False))

    exclude_id = parse_int(exclude_id)
    if exclude_id:
        query = query.filter(Project.id != exclude_id)

    project_id = parse_int(project_id)
    if project_id:
        query = query.filter(Project.id == project_id)

    if project_name:
        query = query.filter(func.lower(Project.name) == project_name.lower())

    if search:
        terms = re.split("[/ ]", search)
        for term in terms:
            if not term:
                continue
            term = escape_for_like(term)
            query = query.filter(or_(
                 Project.name.ilike("%{}%".format(term)),
                 ProjectVersion.name.ilike("%{}%".format(term))))

    if basemirror_id:
        query = query.filter(ProjectVersion.base_mirror_id == basemirror_id)
    else:
        if is_basemirror:
            query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")
        else:
            query = query.filter(Project.is_mirror.is_(False))

    if dependant_id:
        p_version = db.query(ProjectVersion).filter(ProjectVersion.id == dependant_id).first()
        projectversions = []
        if p_version:
            projectversions = [p_version.basemirror]
        nb_projectversions = len(projectversions)
    else:
        query = query.order_by(func.lower(Project.name), func.lower(ProjectVersion.name))
        projectversions = query.all()
        nb_projectversions = query.count()

    results = []

    for projectversion in projectversions:
        projectversion_dict = projectversion.data()
        results.append(projectversion_dict)

    data = {"total_result_count": nb_projectversions, "results": results}

    return OKResponse(data)


async def do_overlay(request, projectversion_id, name):
    if not name:
        return ErrorResponse(400, "No valid name for the projectversion received")
    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    db = request.cirrina.db_session
    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    overlay_projectversion = db.query(ProjectVersion).filter(func.lower(ProjectVersion.name) == name.lower(),
                                                             ProjectVersion.project_id == projectversion.project_id).first()
    if overlay_projectversion:
        return ErrorResponse(400, "Overlay already exists")

    overlay_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        # add the projectversion where the overlay is created from as a dependency
        dependencies=[projectversion],
        mirror_architectures=projectversion.mirror_architectures,
        basemirror=projectversion.basemirror,
        description=projectversion.description,
        dependency_policy=projectversion.dependency_policy,
        ci_builds_enabled=projectversion.ci_builds_enabled,
        projectversiontype="overlay",
        baseprojectversion_id=projectversion.id
    )

    db.add(overlay_projectversion)
    db.commit()

    basemirror = overlay_projectversion.basemirror

    await enqueue_aptly({"init_repository": [
                basemirror.project.name,
                basemirror.name,
                overlay_projectversion.project.name,
                overlay_projectversion.name,
                db2array(overlay_projectversion.mirror_architectures),
                []]})

    return OKResponse({"id": overlay_projectversion.id, "name": overlay_projectversion.name})


@app.http_post("/api/projectversions/{projectversion_id}/toggleci")
@req_role("owner")
async def post_projectversion_toggle_ci(request):
    """
    Toggles the ci enabled flag on a projectversion.

    ---
    description: Toggles the ci enabled flag on a projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    projectversion_id = request.match_info["projectversion_id"]
    try:
        projectversion_id = int(projectversion_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for projectversion_id")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id))

    projectversion.ci_builds_enabled = not projectversion.ci_builds_enabled
    db.commit()

    result = "enabled" if projectversion.ci_builds_enabled else "disabled"

    logger.info("continuous integration builds %s on ProjectVersion '%s/%s'",
                result,
                projectversion.project.name,
                projectversion.name)

    return OKResponse("Ci builds are now {}.".format(result))


def do_lock(request, projectversion_id):
    db = request.cirrina.db_session
    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id))

    deps = get_projectversion_deps(projectversion.id, db)
    for d in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d[0]).first()
        if dep and not dep.is_locked:
            return ErrorResponse(400, "Dependencies of given projectversion must be locked")

    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False
    db.commit()

    logger.info("ProjectVersion '%s/%s' locked", projectversion.project.name, projectversion.name)
    return OKResponse("Locked Project Version")


def do_unlock(request, projectversion_id):
    db = request.cirrina.db_session
    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id))

    projectversion.is_locked = False
    projectversion.ci_builds_enabled = False
    db.commit()

    logger.info("ProjectVersion '%s/%s' unlocked", projectversion.project.name, projectversion.name)
    return OKResponse("Unlocked Project Version")
