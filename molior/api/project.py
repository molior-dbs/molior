from aiohttp import web
from sqlalchemy import func

from ..app import app, logger
from ..auth import req_role, req_admin
from ..molior.configuration import Configuration
from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_projectversion_deps, get_projectversion
from ..tools import ErrorResponse, paginate, is_name_valid, OKResponse


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
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    filter_name = request.GET.getone("q", "")

    query = db.query(Project).filter(Project.is_mirror.is_(False)).order_by(Project.name)

    if filter_name:
        query = query.filter(Project.name.ilike("%{}%".format(filter_name)))

    nb_results = query.count()
    query = paginate(request, query)
    results = query.all()

    data = {"total_result_count": nb_results}
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
    db = request.cirrina.db_session
    project_id = request.match_info["project_id"]
    show_deleted = request.GET.getone("show_deleted", "").lower() == "true"
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for project_id")

    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        return ErrorResponse(404, "Project with id {} could not be found!".format(project_id))

    versions = db.query(ProjectVersion).filter_by(project_id=project.id,
                                                  is_deleted=show_deleted).order_by(func.lower(ProjectVersion.name).desc()).all()
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
    parameters:
        - in: body
          name: body
          description: Created user object
          required: true
          schema:
            type: object
            properties:
              name:
                type: string
              description:
                type: string
    produces:
        - text/json
    """
    db = request.cirrina.db_session
    params = await request.json()
    name = params.get("name")
    description = params.get("description")
    if not name:
        return ErrorResponse(400, "No project name given")

    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    if db.query(Project).filter(func.lower(Project.name) == name.lower()).first():
        return ErrorResponse(400, "Projectname is already taken")

    project = Project(name=name, description=description)
    db.add(project)
    db.commit()

    return web.json_response({"id": project.id, "name": project.name})


@app.http_put("/api/projectbase/{project_id}")
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
    db = request.cirrina.db_session
    # TODO: Implement this api method.
    project_id = request.match_info["project_id"]
    params = await request.json()
    description = params.get("description")

    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for project_id")

    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        return ErrorResponse(404, "project {} not found".format(project_id))
    project.description = description
    db.commit()
    return OKResponse("project updated")


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
    db = request.cirrina.db_session
    project_id = request.match_info["project_id"]
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for project_id")

    project = db.query(Project).filter_by(id=project_id).first()
    if project:
        project.delete()

    return OKResponse("project {} deleted".format(project_id))


@app.http_get("/api/projectsources/{project_name}/{project_version}")
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
        - name: project_version
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
    db = request.cirrina.db_session
    unstable = request.GET.getone("unstable", "")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "projectversion not found")

    deps = [(projectversion.id, projectversion.ci_builds_enabled)]
    deps += get_projectversion_deps(projectversion.id, db)

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public")
    if not apt_url:
        apt_url = cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources_list = "# APT Sources for project {0} {1}\n".format(projectversion.project.name, projectversion.name)
    sources_list += "# GPG-Key: {0}/{1}\n".format(apt_url, keyfile)
    if not projectversion.project.is_basemirror and projectversion.basemirror:
        sources_list += "# Base Mirror\n"
        sources_list += "{}\n".format(projectversion.basemirror.get_apt_repo())

    sources_list += "# Project Sources\n"
    for d in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d[0]).first()
        if not dep:
            logger.error("projectsources: projecversion %d not found", d[0])
        sources_list += "{}\n".format(dep.get_apt_repo())
        # ci builds requested & use ci builds from this dep & dep has ci builds
        if unstable == "true" and d[1] and dep.ci_builds_enabled:
            sources_list += "{}\n".format(dep.get_apt_repo(dist="unstable"))

    return web.Response(status=200, text=sources_list)
