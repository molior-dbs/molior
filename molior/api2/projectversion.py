from sqlalchemy.sql import or_

from ..app import app, logger
from ..auth import req_role
from ..tools import ErrorResponse, parse_int, is_name_valid, paginate, OKResponse, array2db
from ..api.projectversion import projectversion_to_dict
from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_projectversion, get_projectversion_deps, get_projectversion_byname


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
    db = request.cirrina.db_session
    project_id = request.match_info["project_id"]
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    filter_name = request.GET.getone("q", None)

    query = db.query(ProjectVersion).join(Project).filter(Project.is_mirror is False)
    if project_id:
        query = query.filter(or_(Project.name == project_id, Project.id == parse_int(project_id)))
    if filter_name:
        query = query.filter(ProjectVersion.name.like("%{}%".format(filter_name)))
    if basemirror_id:
        query = query.filter(ProjectVersion.basemirror_id == basemirror_id)
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")

    query = query.order_by(ProjectVersion.id.desc())

    nb_projectversions = query.count()
    query = paginate(request, query)
    projectversions = query.all()

    results = []
    for projectversion in projectversions:
        projectversion_dict = projectversion_to_dict(projectversion)
        results.append(projectversion_dict)

    data = {"total_result_count": nb_projectversions, "results": results}

    return OKResponse(data)


@app.http_get("/api2/project/{project_name}/{project_version}")
@app.authenticated
async def get_projectversion2(request):
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
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Projectversion not found")

    data = projectversion_to_dict(projectversion)
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/versions")
@req_role("owner")
async def create_projectversion(request):
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
    db = request.cirrina.db_session
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

    project = db.query(Project).filter(Project.name == project_id).first()
    if not project:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return ErrorResponse(400, "Project '{}' could not be found".format(project_id))

    projectversion = db.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == name, Project.id == project.id).first()
    if projectversion:
        return ErrorResponse(400, "Projectversion already exists{}".format(
                ", and is marked as deleted" if projectversion.is_deleted else ""))

    basemirror = db.query(ProjectVersion).join(Project).filter(
                                    Project.id == ProjectVersion.project_id,
                                    Project.name == basemirror_name,
                                    ProjectVersion.name == basemirror_version).first()
    if not basemirror:
        return ErrorResponse(400, "Base mirror not found: {}/{}".format(basemirror_name, basemirror_version))

    projectversion = ProjectVersion(
            name=name,
            project=project,
            mirror_architectures=array2db(architectures),
            basemirror=basemirror,
            mirror_state=None)
    db.add(projectversion)
    db.commit()

    logger.info("ProjectVersion '%s/%s' with id '%s' added", projectversion.project.name, projectversion.name, projectversion.id)

    await request.cirrina.aptly_queue.put({"init_repository": [
                projectversion.id,
                basemirror_name,
                basemirror_version,
                projectversion.project.name,
                projectversion.name,
                architectures]})

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_get("/api2/project/{project_id}/{projectversion_id}/dependencies")
@app.authenticated
async def get_projectversion_dependencies(request):
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
    db = request.cirrina.db_session
    candidates = request.GET.getone("candidates", None)
    # filter_name = request.GET.getone("q", None)

    if candidates:
        candidates = candidates == "true"

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    # get existing dependencies
    dep_ids = get_projectversion_deps(projectversion.id, db)

    results = []
    if candidates:  # return candidate dependencies
        cands = db.query(ProjectVersion).filter(ProjectVersion.basemirror_id == projectversion.basemirror_id,
                                                ProjectVersion.id != projectversion.id,
                                                ProjectVersion.id.notin_(dep_ids)).all()
        for cand in cands:
            results.append(projectversion_to_dict(cand))

    else:  # return existing dependencies
        deps = db.query(ProjectVersion).filter(ProjectVersion.id.in_(dep_ids)).all()
        for dep in deps:
            if dep:
                results.append(projectversion_to_dict(dep))

    data = {"total_result_count": len(results), "results": results}
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/dependencies")
@req_role("owner")
async def add_projectversion_dependency(request):
    db = request.cirrina.db_session
    params = await request.json()
    dependency_name = params.get("dependency")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.is_locked:
        return ErrorResponse(400, "You can not add dependencies on a locked projectversion")

    dependency = get_projectversion_byname(dependency_name, db)
    if not dependency:
        return ErrorResponse(400, "Dependency not found")

    if dependency.id == projectversion.id:
        return ErrorResponse(400, "You can not add a dependency of the same projectversion to itself")

    # check for dependency loops
    dep_ids = get_projectversion_deps(dependency.id, db)
    if projectversion.id in dep_ids:
        return ErrorResponse(400, "You can not add a dependency of a projectversion depending itself on this projectversion")

    projectversion.dependencies.append(dependency)
    db.commit()
    return OKResponse("Dependency added")


@app.http_delete("/api2/project/{project_id}/{projectversion_id}/dependency/{dependency_name}/{dependency_version}")
@req_role("owner")
async def delete_projectversion_dependency(request):
    db = request.cirrina.db_session
    dependency_name = request.match_info["dependency_name"]
    dependency_version = request.match_info["dependency_version"]

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    dependency = get_projectversion_byname(dependency_name + "/" + dependency_version, db)
    if not dependency:
        return ErrorResponse(400, "Dependency not found")

    projectversion.dependencies.remove(dependency)
    db.commit()
    return OKResponse("Dependency deleted")
