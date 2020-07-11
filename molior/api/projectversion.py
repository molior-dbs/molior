from ..app import app, logger
from ..auth import req_role
from ..tools import ErrorResponse, parse_int, is_name_valid, OKResponse
from ..model.projectversion import ProjectVersion, get_projectversion_deps
from ..model.project import Project
from ..model.sourcerepository import SourceRepository
from ..model.sourepprover import SouRepProVer


def projectversion_to_dict(projectversion):
    """
    Returns the given projectversion object
    as dist, which can be processed by
    json_response
    ---
    Args:
        projectversion (object): The projectversion from the database
            provided by SQLAlchemy.
    Returns:
        dict: The dict which can be processed by json_response

    """
    data = {
        "id": projectversion.id,
        "name": projectversion.name,
        "project_name": projectversion.project.name,
        "apt_url": projectversion.get_apt_repo(url_only=True),
        "project": {
            "id": projectversion.project.id,
            "name": projectversion.project.name,
            "description": projectversion.project.description,
        },
        "architectures": projectversion.mirror_architectures[1:-1].split(","),
        "is_locked": projectversion.is_locked,
        "ci_builds_enabled": projectversion.ci_builds_enabled,
    }
    if projectversion.basemirror:
        data.update({"basemirror": projectversion.basemirror.fullname})

    return data


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
          type: bool
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

    query = db.query(ProjectVersion).filter(ProjectVersion.is_deleted == False)  # noqa: E712

    exclude_id = parse_int(exclude_id)
    if exclude_id:
        query = query.filter(Project.id != exclude_id)

    project_id = parse_int(project_id)
    if project_id:
        query = query.filter(Project.id == project_id)

    if project_name:
        query = query.filter(Project.name == project_name)

    if basemirror_id:
        query = query.filter(ProjectVersion.base_mirror_id == basemirror_id)
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")

    if dependant_id:
        logger.info("dependant_id")
        p_version = db.query(ProjectVersion).filter(ProjectVersion.id == dependant_id).first()
        projectversions = []
        if p_version:
            projectversions = [p_version.basemirror]
        nb_projectversions = len(projectversions)
    else:
        query = query.order_by(Project.name, ProjectVersion.name)
        projectversions = query.all()
        nb_projectversions = query.count()

    results = []

    for projectversion in projectversions:
        projectversion_dict = projectversion_to_dict(projectversion)
        dep_ids = get_projectversion_deps(projectversion.id, db)
        projectversion_dict["dependencies"] = []
        for dep_id in dep_ids:
            dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
            if dep:
                projectversion_dict["dependencies"].append(projectversion_to_dict(dep))
        results.append(projectversion_dict)

    data = {"total_result_count": nb_projectversions, "results": results}

    return OKResponse(data)


@app.http_get("/api/projectversions/{projectversion_id}")
@app.authenticated
async def get_projectversion(request):
    """
    Returns the projectversion.

    ---
    description: Return the projectversion
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
        return ErrorResponse(400, "Projectversion %d not found" % projectversion_id)

    if projectversion.is_deleted:
        return ErrorResponse(404, "Projectversion {} deleted".format(projectversion_id))

    projectversion_dict = projectversion_to_dict(projectversion)
    dep_ids = get_projectversion_deps(projectversion.id, db)
    projectversion_dict["dependencies"] = []
    for dep_id in dep_ids:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
        if dep:
            projectversion_dict["dependencies"].append(projectversion_to_dict(dep))

    projectversion_dict["basemirror_url"] = str()
    if projectversion.basemirror:
        projectversion_dict["basemirror_url"] = projectversion.basemirror.get_apt_repo()

    return OKResponse(projectversion_dict)


@app.http_post("/api/projects/{project_id}/versions")
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

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.name == name, Project.id == project.id).first()
    if projectversion:
        return ErrorResponse(400, "Projectversion already exists{}".format(
                ", and is marked as deleted!" if projectversion.is_deleted else ""))

    basemirror = db.query(ProjectVersion).filter(ProjectVersion.project.name == basemirror_name,
                                                 ProjectVersion.name == basemirror_version).first()
    if not basemirror:
        return ErrorResponse(400, "Base mirror not found: {}/{}".format(basemirror_name, basemirror_version))

    projectversion = ProjectVersion(name=name, project=project, architectures=architectures, basemirror=basemirror)
    db.add(projectversion)
    db.commit()

    logger.info("ProjectVersion '%s/%s' with id '%s' added", projectversion.project.name, projectversion.name, projectversion.id)

    project_name = projectversion.project.name
    project_version = projectversion.name

    await request.cirrina.aptly_queue.put({"init_repository": [
                projectversion.id,
                basemirror_name,
                basemirror_version,
                project_name,
                project_version,
                architectures]})

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_delete("/api/projectversions/{projectversion_id}/repositories/{sourcerepository_id}")
@req_role(["member", "owner"])
async def delete_repository(request):
    """
    Adds given sourcerepositories to the given
    projectversion.

    ---
    description: Adds given sourcerepositories to given projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: sourcerepository_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
    """
    db = request.cirrina.db_session
    projectversion_id = parse_int(request.match_info["projectversion_id"])
    sourcerepository_id = parse_int(request.match_info["sourcerepository_id"])
    projectversion_id = parse_int(projectversion_id)
    if not projectversion_id:
        return ErrorResponse(400, "No valid projectversion_id received")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion {} could not been found.".format(projectversion_id))

    if not sourcerepository_id:
        return ErrorResponse(400, "No valid sourcerepository_id received")

    sourcerepository = db.query(SourceRepository).filter(SourceRepository.id == sourcerepository_id).first()
    if not sourcerepository:
        return ErrorResponse(400, "Sourcerepository {} could not been found".format(sourcerepository_id))

    # get the association of the projectversion and the sourcerepository
    sourcerepositoryprojectversion = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                                   SouRepProVer.projectversion_id == projectversion.id).first()
    if not sourcerepositoryprojectversion:
        return ErrorResponse(400, "Could not find the sourcerepository for the projectversion")

    projectversion.sourcerepositories.remove(sourcerepository)
    db.commit()

    return OKResponse("Sourcerepository removed from projectversion")


@app.http_post("/api/projectversions/{projectversion_id}/clone")
@req_role("owner")
async def clone_projectversion(request):
    """
    Clone a given projectversion

    ---
    description: Toggles the ci enabled flag on a projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                name:
                    type: string
                    example: "1.0.0"
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    params = await request.json()

    name = params.get("name")
    projectversion_id = parse_int(request.match_info["projectversion_id"])

    if not projectversion_id:
        return ErrorResponse(400, "No valid project id received")
    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name!")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()

    if db.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == name,
            Project.id == projectversion.project_id).first():
        return ErrorResponse(400, "Projectversion already exists.")

    new_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        dependencies=projectversion.dependencies,
        mirror_architectures=projectversion.mirror_architectures,
        basemirror_id=projectversion.basemirror_id,
        sourcerepositories=projectversion.sourcerepositories,
        ci_builds_enabled=projectversion.ci_builds_enabled,
    )

    for repo in new_projectversion.sourcerepositories:
        sourepprover = db.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == repo.id,
                SouRepProVer.projectversion_id == projectversion.id).first()
        new_sourepprover = db.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == repo.id,
                SouRepProVer.projectversion_id == new_projectversion.id).first()
        new_sourepprover.architectures = sourepprover.architectures

    db.add(new_projectversion)
    db.commit()

    await request.cirrina.aptly_queue.put(
        {
            "init_repository": [
                new_projectversion.id,
                new_projectversion.basemirror.project.name,
                new_projectversion.basemirror.name,
                new_projectversion.project.name,
                new_projectversion.name,
                new_projectversion.architectures[1:-1].split(","),
            ]
        }
    )

    return OKResponse({"id": new_projectversion.id, "name": new_projectversion.name})


@app.http_post("/api/projectversions/{projectversion_id}/overlay")
@req_role("owner")
async def create_projectversion_overlay(request):
    """
    Creates an overlay of a project version

    ---
    description: Creates an overlay of a project version
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                name:
                    type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    params = await request.json()

    name = params.get("name")
    projectversion_id = parse_int(request.match_info["projectversion_id"])

    if not projectversion_id:
        return ErrorResponse(400, "No valid project id received")
    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    overlay_projectversion = db.query(ProjectVersion).filter(ProjectVersion.name == name,
                                                             ProjectVersion.project_id == projectversion.project_id).first()
    if overlay_projectversion:
        return ErrorResponse(400, "Overlay already exists")

    overlay_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        # add the projectversion where the overlay is created from as a dependency
        dependencies=[projectversion],
        architectures=projectversion.architectures,
        basemirror=projectversion.basemirror
    )

    db.add(overlay_projectversion)
    db.commit()

    basemirror = overlay_projectversion.basemirror
    architectures = overlay_projectversion.architectures[1:-1].split(",")

    await request.cirrina.aptly_queue.put(
        {
            "init_repository": [
                overlay_projectversion.id,
                basemirror.project.name,
                basemirror.name,
                overlay_projectversion.project.name,
                overlay_projectversion.name,
                architectures,
            ]
        }
    )

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


@app.http_post("/api/projectversions/{projectversion_id}/lock")
@req_role("owner")
async def post_projectversion_lock(request):
    """
    Locks a projectversion.

    ---
    description: Locks a projectversion.
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

    dep_ids = get_projectversion_deps(projectversion.id, db)
    for dep_id in dep_ids:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
        if dep and not dep.is_locked:
            return ErrorResponse(400, "Dependencies of given projectversion must be locked")

    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False
    db.commit()

    logger.info("ProjectVersion '%s/%s' locked", projectversion.project.name, projectversion.name)
    return OKResponse("Locked Project Version")


@app.http_put("/api/projectversions/{projectversion_id}/mark-delete")
@req_role("owner")
async def mark_delete_projectversion(request):
    """
    Marks a projectversion as deleted.

    ---
    description: Deletes a projectversion.
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
        logger.error("projectversion mark delete: invalid projectversion_id %s", projectversion_id)
        return ErrorResponse(400, "invalid projectversion_id")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        logger.error("projectversion mark delete: projectversion_id %d not found", projectversion_id)
        return ErrorResponse(400, "Projectversion#{projectversion_id} not found".format(projectversion_id=projectversion_id))

    if projectversion.dependents:
        blocking_dependants = []
        for d in projectversion.dependents:
            if not d.is_deleted:
                blocking_dependants.append("{}/{}".format(d.project.name, d.name))
        if blocking_dependants:
            logger.error("projectversion mark delete: projectversion_id %d still has dependency %d", projectversion_id, d.id)
            return ErrorResponse(400, "Projectversions '{}' are still depending on this version, cannot delete it".format(
                                  ", ".join(blocking_dependants)))

    base_mirror_name = projectversion.basemirror.project.name
    base_mirror_version = projectversion.basemirror.name

    args = {
        "drop_publish": [
            base_mirror_name,
            base_mirror_version,
            projectversion.project.name,
            projectversion.name,
            "stable",
        ]
    }
    await request.cirrina.aptly_queue.put(args)
    args = {
        "drop_publish": [
            base_mirror_name,
            base_mirror_version,
            projectversion.project.name,
            projectversion.name,
            "unstable",
        ]
    }
    await request.cirrina.aptly_queue.put(args)

    projectversion.is_deleted = True
    # lock the projectversion so no packages can be published in this repository
    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False
    db.commit()

    logger.info("ProjectVersion '%s/%s' deleted", projectversion.project.name, projectversion.name)
    return OKResponse("Deleted Project Version")


@app.http_delete("/api/projectversions/{projectversion_id}/dependency")
@req_role("owner")
async def delete_projectversion_dependency(request):
    """
    Deletes a projectversion dependency.

    ---
    description: Deletes a dependency of a projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                dependency_id:
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
    params = await request.json()

    projectversion_id = parse_int(request.match_info["projectversion_id"])
    if not projectversion_id:
        return ErrorResponse(400, "Incorrect value for projectversion_id")

    dependency_id = parse_int(params.get("dependency_id"))
    if not dependency_id:
        return ErrorResponse(400, "Incorrect value for dependency_id")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Could not find projectversion with id: {}".format(projectversion_id))

    if projectversion.is_locked:
        return ErrorResponse(400, "You can not delete dependencies on a locked projectversion")

    dependency = db.query(ProjectVersion).filter(ProjectVersion.id == dependency_id).first()
    if not dependency:
        return ErrorResponse(400, "Could not find projectversion dependency with id: {}".format(dependency_id))

    projectversion.dependencies.remove(dependency)

    pv_name = "{}/{}".format(projectversion.project.name, projectversion.name)
    dep_name = "{}/{}".format(dependency.project.name, dependency.name)

    db.commit()
    logger.info("ProjectVersionDependency '%s -> %s' deleted", pv_name, dep_name)
    return OKResponse("Deleted dependency from {} to {}".format(pv_name, dep_name))


@app.http_post("/api/projectversions/{projectversion_id}/dependency")
@app.authenticated
@req_role("owner")
async def post_projectversion_dependency(request):
    """
    Adds a projectversiondependency to a projectversion.

    ---
    description: Return the projectversion
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                dependency_id:
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
    params = await request.json()

    projectversion_id = parse_int(request.match_info["projectversion_id"])
    if not projectversion_id:
        return ErrorResponse(400, "Incorrect value for projectversion_id")

    dependency_id = parse_int(params.get("dependency_id"))
    if not dependency_id:
        return ErrorResponse(400, "Incorrect value for dependency_id")

    projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not projectversion:
        return ErrorResponse(400, "Invalid data received")

    if projectversion.is_locked:
        return ErrorResponse(400, "You can not add dependencies on a locked projectversion")

    if dependency_id == projectversion_id:
        return ErrorResponse(400, "You can not add a dependency of the same projectversion to itself")

    dependency = db.query(ProjectVersion).filter(ProjectVersion.id == dependency_id).first()
    if not dependency:
        return ErrorResponse(400, "Invalid data received")

    # check for dependency loops
    dep_ids = get_projectversion_deps(dependency_id, db)
    if projectversion_id in dep_ids:
        return ErrorResponse(400, "You can not add a dependency of a projectversion depending itself on this projectversion")

    projectversion.dependencies.append(dependency)
    db.commit()

    return OKResponse("Dependency added")
