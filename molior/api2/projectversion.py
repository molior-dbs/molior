from aiohttp import web
from sqlalchemy.sql import or_

from molior.app import app, logger
from molior.auth import req_role
from molior.model.projectversion import ProjectVersion
from molior.model.project import Project
from molior.model.buildvariant import BuildVariant
from molior.tools import ErrorResponse, parse_int, get_buildvariants, is_name_valid, paginate

from ..api.projectversion import projectversion_to_dict


@app.http_get("/api2/project/{project_id}/versions")
@app.authenticated
async def get_projectversions2(request):
    """
    Returns a list of projectversions.

    ---
    description: Returns a list of projectversions.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: basemirror_id
          in: query
          required: false
          type: integer
        - name: is_basemirror
          in: query
          required: false
          type: bool
        - name: project_id
          in: query
          required: false
          type: integer
        - name: project_name
          in: query
          required: false
          type: string
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
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
    project_id = request.match_info["project_id"]
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    filter_name = request.GET.getone("q", None)

    query = request.cirrina.db_session.query(ProjectVersion).join(Project)
    if project_id:
        query = query.filter(or_(Project.name == project_id, Project.id == parse_int(project_id)))
    if filter_name:
        query = query.filter(ProjectVersion.name.like("%{}%".format(filter_name)))
    if basemirror_id:
        query = query.filter(ProjectVersion.buildvariants.any(BuildVariant.base_mirror_id == basemirror_id))
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")  # pylint: disable=no-member

    query = query.order_by(Project.name, ProjectVersion.name)
    query = paginate(request, query)

    projectversions = query.all()
    nb_projectversions = query.count()

    results = []

    for projectversion in projectversions:
        projectversion_dict = projectversion_to_dict(projectversion)
        results.append(projectversion_dict)

    data = {"total_result_count": nb_projectversions, "results": results}

    return web.json_response(data)


@app.http_get("/api2/project/{project_name}/{project_version}")
@app.authenticated
async def get_projectversion_byname(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
        - name: project_version
          in: path
          required: true
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "404":
            description: no entry found
    """

    project_name = request.match_info["project_name"]
    project_version = request.match_info["project_version"]

    projectversion = request.cirrina.db_session.query(ProjectVersion).filter(
            ProjectVersion.name == project_version).join(Project).filter(
            Project.name == project_name).first()
    if not projectversion:
        return ErrorResponse(404, "Project with name {} could not be found!".format(project_name))

    data = projectversion_to_dict(projectversion)
    return web.json_response(data)


@app.http_post("/api2/project/{project_id}/versions")
@req_role("owner")
async def create_projectversions(request):
    """
    Creates a new projectversion.

    ---
    description: Creates a new projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: project
          in: path
          required: true
          type: string
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                name:
                    type: string
                    example: "1.0.0"
                basemirror:
                    type: string
                    example: "stretch/9.6"
                architectures:
                    type: array
                    example: ["amd64", "armhf"]
                    FIXME: only accept existing archs on mirror!
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: invalid data received
        "500":
            description: internal server error
    """
    params = await request.json()

    name = params.get("name")
    architectures = params.get("architectures", [])
    basemirror = params.get("basemirror")
    project_id = request.match_info["project_id"]

    if not project_id:
        return ErrorResponse(400, "No valid project id received")
    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not basemirror or not ("/" in basemirror):
        return ErrorResponse(400, "No valid basemirror received (format: 'name/version')")
    if not architectures:
        return ErrorResponse(400, "No valid architecture received")

    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name!")

    basemirror_name, basemirror_version = basemirror.split("/")

    # FIXME: verify valid architectures

    project = request.cirrina.db_session.query(Project).filter(Project.name == project_id).first()
    if not project:
        project = request.cirrina.db_session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return ErrorResponse(400, "Project '{}' could not be found".format(project_id))

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .join(Project)
        .filter(ProjectVersion.name == name)
        .filter(Project.id == project.id)
        .first()
    )
    if projectversion:
        return ErrorResponse(400, "Projectversion already exists. {}".format(
                "And is marked as deleted!" if projectversion.is_deleted else ""))

    buildvariants = get_buildvariants(request.cirrina.db_session, basemirror_name, basemirror_version, architectures)

    projectversion = ProjectVersion(name=name, project=project)
    projectversion.buildvariants = buildvariants
    request.cirrina.db_session.add(projectversion)
    request.cirrina.db_session.commit()

    logger.info("ProjectVersion '%s/%s' with id '%s' added",
                projectversion.project.name,
                projectversion.name,
                projectversion.id,
                )

    project_name = projectversion.project.name
    project_version = projectversion.name

    await request.cirrina.aptly_queue.put({"init_repository": [
                projectversion.id,
                basemirror_name,
                basemirror_version,
                project_name,
                project_version,
                architectures]})

    return web.json_response({"id": projectversion.id, "name": projectversion.name})
