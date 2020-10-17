from sqlalchemy.orm import aliased
from sqlalchemy import func

from ..app import app, logger
from ..auth import req_role
from ..tools import ErrorResponse, OKResponse, is_name_valid, db2array
from ..api.projectversion import do_clone, do_lock, do_overlay

from ..model.projectversion import ProjectVersion, get_projectversion, get_projectversion_deps, get_projectversion_byname
from ..model.project import Project
from ..model.sourepprover import SouRepProVer
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.postbuildhook import PostBuildHook
from ..model.projectversiondependency import ProjectVersionDependency


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

    return OKResponse(projectversion.data())


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
    filter_name = request.GET.getone("q", None)

    if candidates:
        candidates = candidates == "true"

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    # get existing dependencies
    deps = get_projectversion_deps(projectversion.id, db)
    dep_ids = [d[0] for d in deps]

    results = []
    if candidates:  # return candidate dependencies
        cands_query = db.query(ProjectVersion).filter(ProjectVersion.basemirror_id == projectversion.basemirror_id,
                                                      ProjectVersion.id != projectversion.id,
                                                      ProjectVersion.id.notin_(dep_ids))
        BaseMirror = aliased(ProjectVersion)
        dist_query = db.query(ProjectVersion).join(BaseMirror, BaseMirror.id == ProjectVersion.basemirror_id).filter(
                                                   ProjectVersion.dependency_policy == "distribution",
                                                   BaseMirror.project_id == projectversion.basemirror.project_id,
                                                   BaseMirror.id != projectversion.basemirror_id,
                                                   ProjectVersion.id.notin_(dep_ids))

        any_query = db.query(ProjectVersion).filter(
                                                   ProjectVersion.dependency_policy == "any",
                                                   ProjectVersion.id != projectversion.id,
                                                   ProjectVersion.id.notin_(dep_ids))
        cands = cands_query.union(dist_query, any_query).join(Project).order_by(Project.is_mirror,
                                                                                Project.name,
                                                                                ProjectVersion.name.asc())
        if filter_name:
            cands = cands.filter(ProjectVersion.fullname.like("%{}%".format(filter_name)))

        for cand in cands.all():
            results.append(cand.data())

    else:  # return existing dependencies
        deps = db.query(ProjectVersion).filter(ProjectVersion.id.in_(dep_ids))
        if filter_name:
            deps = deps.filter(ProjectVersion.fullname.like("%{}%".format(filter_name)))
        for dep in deps.all():
            if dep:
                results.append(dep.data())

    data = {"total_result_count": len(results), "results": results}
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/dependencies")
@req_role("owner")
async def add_projectversion_dependency(request):
    db = request.cirrina.db_session
    params = await request.json()
    dependency_name = params.get("dependency")
    use_cibuilds = params.get("use_cibuilds")

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
    deps = get_projectversion_deps(dependency.id, db)
    dep_ids = [d[0] for d in deps]
    if projectversion.id in dep_ids:
        return ErrorResponse(400, "Cannot add a dependency of a projectversion depending itself on this projectversion")

    pdep = ProjectVersionDependency(
            projectversion_id=projectversion.id,
            dependency_id=dependency.id,
            use_cibuilds=use_cibuilds)
    db.add(pdep)
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

    # find latest builds
    latest_builds = db.query(func.max(Build.id).label("latest_id")).filter(
            Build.projectversion_id == projectversion.id,
            Build.buildtype == "deb").group_by(Build.sourcerepository_id).subquery()

    builds = db.query(Build).join(latest_builds, Build.id == latest_builds.c.latest_id).order_by(
            Build.sourcename, Build.id.desc()).all()

    packages = []
    build_source_names = []
    for build in builds:
        logger.info("snapshot: found latest build: %s/%s (%s)" % (build.sourcename, build.version, build.buildstate))
        if build.buildstate != "successful":
            return ErrorResponse(400, "Not all latest builds are successful")
        if build.sourcename in build_source_names:
            logger.warning("shapshot: ignoring duplicate build sourcename: %s/%s" % (build.sourcename, build.version))
            continue
        build_source_names.append(build.sourcename)
        if not build.debianpackages:
            return ErrorResponse(400, "No debian packages found for %s/%s" % (build.sourcename, build.version))
        for deb in build.debianpackages:
            logger.info("deb %s_%s_%s.deb" % (deb.name, build.version, deb.suffix))
            packages.append((deb.name, build.version, deb.suffix))

    new_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        dependencies=projectversion.dependencies,   # FIXME: use_cubilds not included via relationship
        mirror_architectures=projectversion.mirror_architectures,
        basemirror_id=projectversion.basemirror_id,
        sourcerepositories=projectversion.sourcerepositories,
        ci_builds_enabled=False,
        is_locked=True,
        # FIXME: is_snapshot=True, snapshot origin
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
            "snapshot_repository": [
                projectversion.basemirror.project.name,
                projectversion.basemirror.name,
                projectversion.project.name,
                projectversion.name,
                db2array(projectversion.mirror_architectures),
                new_projectversion.name,
                packages
            ]
        }
    )

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
        buildtasks = db.query(BuildTask).filter(BuildTask.build == build).all()
        for buildtask in buildtasks:
            db.delete(buildtask)
        db.delete(build)
        if parent:
            buildtasks = db.query(BuildTask).filter(BuildTask.build == parent.parent).all()
            for buildtask in buildtasks:
                db.delete(buildtask)
            db.delete(parent.parent)
            buildtasks = db.query(BuildTask).filter(BuildTask.build == parent).all()
            for buildtask in buildtasks:
                db.delete(buildtask)
            db.delete(parent)

    # delete hooks
    sourcerepositoryprojectversions = db.query(SouRepProVer).filter(SouRepProVer.projectversion_id == projectversion.id).all()
    for sourcerepositoryprojectversion in sourcerepositoryprojectversions:
        hooks = db.query(PostBuildHook).filter(PostBuildHook.sourcerepositoryprojectversion_id ==
                                               sourcerepositoryprojectversion.id).all()
        for hook in hooks:
            db.delete(hook)

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
