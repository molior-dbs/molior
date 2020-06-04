from aiohttp import web

from molior.app import app, logger
from molior.auth import req_role, req_admin
from molior.molior.configuration import Configuration
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion
from molior.tools import ErrorResponse, paginate, is_name_valid

from .projectversion import get_projectversion_deps_manually


@app.http_get("/api/projects")
@app.authenticated
async def get_projects(request):
    """
    Return a list of projects.

    ---
    description: Returns a list of projects.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: q
          in: query
          required: false
          type: string
        - name: count_only
          in: query
          required: false
          type: boolean
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    filter_name = request.GET.getone("q", "")
    try:
        count_only = request.GET.getone("count_only").lower() == "true"
    except (ValueError, KeyError):
        count_only = False

    query = (
        request.cirrina.db_session.query(Project)  # pylint: disable=no-member
        .filter(Project.is_mirror.is_(False))
        .order_by(Project.name)
    )

    if filter_name:
        query = query.filter(Project.name.like("%{}%".format(filter_name)))

    nb_results = query.count()
    query = paginate(request, query)
    results = query.all()

    data = {"total_result_count": nb_results}
    if not count_only:
        data["results"] = [
            {"id": item.id, "name": item.name, "description": item.description}
            for item in results
        ]

    return web.json_response(data)


@app.http_get("/api/projects/{project_id}")
@app.authenticated
async def get_project(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: show_deleted
          in: query
          required: false
          type: bool
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """

    project_id = request.match_info["project_id"]
    show_deleted = request.GET.getone("show_deleted", "").lower() == "true"
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for project_id")

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return ErrorResponse(404, "Project with id {} could not be found!".format(project_id))

    versions = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter_by(project_id=project.id)
        .filter_by(is_deleted=show_deleted)
        .order_by(ProjectVersion.name.desc())
        .all()
    )

    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "versions": [
            {"id": version.id, "name": version.name, "is_locked": version.is_locked}
            for version in versions
        ],
        "versions_map": {version.id: version.name for version in versions},
    }

    return web.json_response(data)


@app.http_post("/api/projects")
@req_admin
# FIXME: req_role
async def create_project(request):
    """
    Creates a new project.

    ---
    description: Creates a new project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: true
          type: string
        - name: description
          in: query
          required: false
          type: string
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
    description = params.get("description")
    if not name:
        return web.Response(status=400, text="No project name given.")

    if not is_name_valid(name):
        return web.Response(status=400, text="Invalid project name!")

    if (
        request.cirrina.db_session.query(Project)  # pylint: disable=no-member
        .filter(Project.name == name)
        .first()
    ):
        return web.Response(status=400, text="Projectname is already taken")

    project = Project(name=name, description=description)
    request.cirrina.db_session.add(project)
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    logger.info("Project '%s' with id '%s' created", project.name, project.id)

    return web.json_response({"id": project.id, "name": project.name})


@app.http_put("/api/project/{project_id}")
@app.http_put("/api/projects/{project_id}")
@app.authenticated
@req_role("owner")
async def update_project(request):
    """
    Update a project.

    ---
    description: Update a project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: description
          in: query
          required: false
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    # TODO: Implement this api method.
    project_id = request.match_info["project_id"]
    params = await request.json()
    description = params.get("description")

    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for project_id", status=400)

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return web.Response(text="project {} not found".format(project_id), status=400)
    project.description = description
    request.cirrina.db_session.commit()
    return web.Response(status=200)


@app.http_delete("/api/projects/{project_id}")
@app.authenticated
# FIXME: req_role
async def delete_project(request):
    """
    Removes a project from the database.

    ---
    description: Deletes a project with the given id.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: project id could not be found
    """

    project_id = request.match_info["project_id"]
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for project_id", status=400)

    project = (
        request.cirrina.db_session.query(Project)  # pylint: disable=no-member
        .filter_by(id=project_id)
        .first()
    )
    if project:
        project.delete()

    return web.Response(text="project {} deleted".format(project_id), status=200)


@app.http_get("/api/projectsources/{project_name}/{projectver_name}")
async def get_apt_sources(request):
    """
    Returns apt sources list for given project,
    projectversion and distrelease.

    ---
    description: Returns apt sources list.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_name
          in: path
          required: true
          type: str
        - name: projectver_name
          in: path
          required: true
          type: str
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Parameter missing
    """
    project_name = request.match_info.get("project_name")
    projectver_name = request.match_info.get("projectver_name")

    if not project_name or not projectver_name:
        return web.Response(text="Parameter missing", status=400)

    project = (
        request.cirrina.db_session.query(Project)  # pylint: disable=no-member
        .filter(Project.name == project_name)
        .first()
    )
    if not project:
        return web.Response(text=str(), status=400)

    version = (
        request.cirrina.db_session.query(ProjectVersion)  # pylint: disable=no-member
        .filter_by(project_id=project.id)
        .filter(ProjectVersion.name == projectver_name)
        .first()
    )

    if not version:
        return web.Response(text=str(), status=400)

    deps = [version]
    deps += get_projectversion_deps_manually(version, to_dict=False)

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources_list = "# APT Sources for project {0} {1}\n".format(
        project_name, projectver_name
    )
    sources_list += "# GPG-Key: {0}/{1}\n".format(apt_url, keyfile)
    if not project.is_basemirror and version.buildvariants:
        sources_list += "# Base Mirror\n"
        base_mirror = version.buildvariants[0].base_mirror
        sources_list += "{}\n".format(base_mirror.get_apt_repo())

    sources_list += "# Project Sources\n"
    for dep in deps:
        sources_list += "{}\n".format(dep.get_apt_repo())

    return web.Response(text=sources_list, status=200)
