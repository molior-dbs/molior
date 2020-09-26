from ..app import app, logger
from ..auth import req_role
from ..tools import ErrorResponse, OKResponse, is_name_valid, db2array
from ..api.projectversion import projectversion_to_dict, do_clone, do_lock, do_overlay

from ..model.projectversion import ProjectVersion, get_projectversion, get_projectversion_deps, get_projectversion_byname
from ..model.project import Project
from ..model.sourepprover import SouRepProVer
from ..model.build import Build


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
        return ErrorResponse(400, "Cannot add dependencies on a locked projectversion")

    dependency = get_projectversion_byname(dependency_name, db)
    if not dependency:
        return ErrorResponse(400, "Dependency not found")

    if dependency.id == projectversion.id:
        return ErrorResponse(400, "Cannot add a dependency of the same projectversion to itself")

    # check for dependency loops
    dep_ids = get_projectversion_deps(dependency.id, db)
    if projectversion.id in dep_ids:
        return ErrorResponse(400, "Cannot add a dependency of a projectversion depending itself on this projectversion")

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


@app.http_post("/api2/project/{project_id}/{projectversion_id}/clone")
@req_role("owner")
async def clone_projectversion(request):
    params = await request.json()

    name = params.get("name")
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    return await do_clone(request, projectversion.id, name)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/lock")
@req_role("owner")
async def lock_projectversion(request):
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    return do_lock(request, projectversion.id)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/overlay")
@req_role("owner")
async def overlay_projectversion(request):
    params = await request.json()

    name = params.get("name")
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    return await do_overlay(request, projectversion.id, name)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/snapshot")
@req_role("owner")
async def snapshot_projectversion(request):
    params = await request.json()

    name = params.get("name")
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    db = request.cirrina.db_session
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
        ci_builds_enabled=False,
        is_locked=True,
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
                new_projectversion.basemirror.project.name,
                new_projectversion.basemirror.name,
                new_projectversion.project.name,
                new_projectversion.name,
                db2array(new_projectversion.mirror_architectures),
            ]
        }
    )

    # FIXME:
    # re publich latest build

    return OKResponse({"id": new_projectversion.id, "name": new_projectversion.name})


@app.http_delete("/api2/project/{project_id}/{projectversion_id}")
@req_role("owner")
async def delete_projectversion(request):
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    if projectversion.dependents:
        blocking_dependants = []
        for d in projectversion.dependents:
            if not d.is_deleted:
                blocking_dependants.append("{}/{}".format(d.project.name, d.name))
                logger.error("projectversion delete: projectversion_id %d still has dependency %d", projectversion.id, d.id)
        if blocking_dependants:
            return ErrorResponse(400, "Projectversions '{}' are still depending on this version, cannot delete it".format(
                                  ", ".join(blocking_dependants)))

    projectversion.is_deleted = True
    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False
    request.cirrina.db_session.commit()

    basemirror_name = projectversion.basemirror.project.name
    basemirror_version = projectversion.basemirror.name
    project_name = projectversion.project.name
    project_version = projectversion.name
    architectures = db2array(projectversion.mirror_architectures)

    db = request.cirrina.db_session

    # delete builds
    builds = db.query(Build).filter(Build.projectversion_id == projectversion.id).all()
    for build in builds:
        parent = None
        if len(build.parent.children) == 1:
            parent = build.parent
        db.delete(build)
        if parent:
            db.delete(parent.parent)
            db.delete(parent)

    # delete hooks
    # delete sourcerepos

    # delete projectversion
    db.delete(projectversion)

    db.commit()

    await request.cirrina.aptly_queue.put(
        {
            "delete_repository": [
                basemirror_name,
                basemirror_version,
                project_name,
                project_version,
                architectures
            ]
        }
    )
    logger.info("ProjectVersion '%s/%s' deleted", project_name, project_version)
    return OKResponse("Deleted Project Version")
