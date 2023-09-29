from sqlalchemy.orm import aliased
from sqlalchemy import func, or_
from aiohttp import web
from pathlib import Path
from aiofile import AIOFile, Writer
from launchy import Launchy

from ..app import app
from ..logger import logger
from ..auth import req_role, req_admin
from ..tools import ErrorResponse, OKResponse, is_name_valid, db2array, array2db, escape_for_like
from ..api.projectversion import do_lock, do_unlock, do_overlay
from ..molior.queues import enqueue_aptly
from ..molior.configuration import Configuration
from ..aptly import get_aptly_connection

from ..model.projectversion import (
    ProjectVersion, get_projectversion, get_projectversion_deps,
    get_projectversion_byname, get_projectversion_byid)
from ..model.project import Project
from ..model.sourcerepository import SourceRepository
from ..model.sourepprover import SouRepProVer
from ..model.build import Build
from ..model.projectversiondependency import ProjectVersionDependency
from ..model.database import Session
from ..model.metadata import MetaData


# find latest builds
def latest_project_builds(db, projectversion_id):
    latest_builds_subq = db.query(func.max(Build.id).label("latest_id")).filter(
            Build.projectversion_id == projectversion_id,
            Build.is_ci.is_(False),
            Build.sourcerepository_id.isnot(None),
            Build.buildtype == "deb",
            Build.buildstate == "successful").group_by(Build.sourcerepository_id)

    SourceBuild = aliased(Build)

    latest_build_uploads_subq = db.query(func.max(Build.id).label("latest_id")).join(
            SourceBuild, SourceBuild.id == Build.parent_id).filter(
            Build.projectversion_id == projectversion_id,
            Build.is_ci.is_(False),
            Build.sourcerepository_id.is_(None),
            Build.buildtype == "deb",
            Build.buildstate == "successful").group_by(SourceBuild.sourcename)

    latest_union_builds_subq = latest_builds_subq.union_all(latest_build_uploads_subq).subquery()

    return db.query(Build).join(latest_union_builds_subq, Build.id == latest_union_builds_subq.c.latest_id).order_by(
                    Build.sourcename, Build.id.desc()).all()


@app.http_get("/api2/project/{project_name}/{project_version}")
async def get_projectversion2(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
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
        "400":
            description: Projectversion not found
    """
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Projectversion is mirror")

    return OKResponse(projectversion.data())


@app.http_get("/api2/project/{project_id}/{projectversion_id}/dependencies")
@app.authenticated
async def get_projectversion_dependencies(request):
    """
    Returns a list of project version dependencies.

    ---
    description: Returns a list of project version dependencies.
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: candidates
          in: query
          required: false
          type: boolean
        - name: q
          in: query
          required: false
          type: string
          description: Filter query
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
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
    deps = projectversion.dependencies
    dep_ids = [d.id for d in deps]

    if candidates:  # return candidate dependencies
        results = []
        cands_query = db.query(ProjectVersion).filter(ProjectVersion.basemirror_id == projectversion.basemirror_id,
                                                      ProjectVersion.id != projectversion.id,
                                                      ProjectVersion.id.notin_(dep_ids))
        if filter_name:
            cands_query = cands_query.filter(ProjectVersion.fullname.ilike("%{}%".format(escape_for_like(filter_name))))

        BaseMirror = aliased(ProjectVersion)
        dist_query = db.query(ProjectVersion).join(BaseMirror, BaseMirror.id == ProjectVersion.basemirror_id).filter(
                                                   ProjectVersion.dependency_policy == "distribution",
                                                   BaseMirror.project_id == projectversion.basemirror.project_id,
                                                   BaseMirror.id != projectversion.basemirror_id,
                                                   ProjectVersion.id.notin_(dep_ids))

        if filter_name:
            dist_query = dist_query.filter(ProjectVersion.fullname.ilike("%{}%".format(escape_for_like(filter_name))))

        any_query = db.query(ProjectVersion).filter(
                                                   ProjectVersion.dependency_policy == "any",
                                                   ProjectVersion.id != projectversion.id,
                                                   ProjectVersion.id.notin_(dep_ids))
        if filter_name:
            any_query = any_query.filter(ProjectVersion.fullname.ilike("%{}%".format(escape_for_like(filter_name))))

        # cands = cands_query.union(dist_query, any_query).join(Project).order_by(Project.is_mirror,
        #                                                                         func.lower(Project.name),
        #                                                                         func.lower(ProjectVersion.name))
        # if filter_name:
        #     cands = cands.filter(ProjectVersion.fullname.ilike("%{}%".format(filter_name)))

        # for cand in cands.all():

        for cand in cands_query.all():
            results.append(cand.data())

        for cand in dist_query.all():
            results.append(cand.data())

        for cand in any_query.all():
            results.append(cand.data())

        data = {"total_result_count": len(results), "results": results}
        return OKResponse(data)

    # return existing dependencies
    results = []
    # send unique deps
    deps_unique = []
    for d in deps:
        if d not in deps_unique:
            deps_unique.append(d)
    for d in deps_unique:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d.id)
        if filter_name:
            dep = dep.filter(ProjectVersion.fullname.ilike("%{}%".format(filter_name)))
        dep = dep.first()
        if dep:
            data = dep.data()
            results.append(data)

    # FIXME paginate ??
    data = {"total_result_count": len(results), "results": results}
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/dependencies")
@req_role("owner")
async def add_projectversion_dependency(request):
    """
    Add project version dependencies.

    ---
    description: Add project version dependencies.
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          description: Dependency data
          required: true
          schema:
              type: object
              properties:
                  dependency:
                      type: string
                      description: Name of the dependency
                  use_cibuilds:
                      type: boolean
                      description: Use CI builds?
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    params = await request.json()
    dependency_name = params.get("dependency")
    use_cibuilds = params.get("use_cibuilds")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Cannot add dependencies to project which is a mirror")

    if projectversion.is_locked:
        return ErrorResponse(400, "Cannot add dependencies on a locked projectversion")

    db = request.cirrina.db_session
    dependency = get_projectversion_byname(dependency_name, db)
    if not dependency:
        return ErrorResponse(400, "Dependency not found")

    if dependency.id == projectversion.id:
        return ErrorResponse(400, "Cannot add a dependency of the same projectversion to itself")

    if dependency.project.is_basemirror:
        return ErrorResponse(400, "Cannot add a dependency which is a basemirror")

    if dependency.dependency_policy == "strict":
        if dependency.basemirror_id != projectversion.basemirror_id:
            return ErrorResponse(400, "Cannot add a dependency with different basemirror as per dependency policy")
    elif dependency.dependency_policy == "distribution":
        if dependency.basemirror.project.id != projectversion.basemirror.project.id:
            return ErrorResponse(400, "Cannot add a dependency from different distribution as per dependency policy")

    # check for dependency loops
    deps = get_projectversion_deps(dependency.id, db)
    dep_ids = [d[0] for d in deps]
    if projectversion.id in dep_ids:
        return ErrorResponse(400, "Cannot add a dependency of a projectversion depending itself on this projectversion")
    if dependency.id in dep_ids:
        return ErrorResponse(400, "Dependency already exists")
    for dep_id in dep_ids:
        dep = get_projectversion_byid(dep_id, db)
        if dep.dependency_policy == "strict":
            if dep.basemirror_id != dependency.basemirror_id:
                return ErrorResponse(400, "Cannot add a dependency with different basemirror as per dependency policy")
        elif dep.dependency_policy == "distribution":
            if dep.basemirror.project.id != dependency.basemirror.project.id:
                return ErrorResponse(400, "Cannot add a dependency from different distribution as per dependency policy")

    # do not allow using a mirror for ci builds
    if dependency.project.is_mirror:
        use_cibuilds = False

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
    """
    Delete a project version dependency.

    ---
    description: Delete a project version dependency.
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: dependency_name
          in: path
          required: true
          type: string
        - name: dependency_version
          in: path
          required: true
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: Dependency deleted
        "400":
            description: Projectversion not found
    """
    db = request.cirrina.db_session
    dependency_name = request.match_info["dependency_name"]
    dependency_version = request.match_info["dependency_version"]

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Cannot delete dependencies from project which is a mirror")

    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    dependency = get_projectversion_byname(dependency_name + "/" + dependency_version, db)
    if not dependency:
        return ErrorResponse(400, "Dependency not found")

    if dependency not in projectversion.dependencies:
        return ErrorResponse(400, "Dependency not found")

    projectversion.dependencies.remove(dependency)
    db.commit()
    return OKResponse("Dependency deleted")


@app.http_post("/api2/project/{project_id}/{projectversion_id}/copy")
@req_role("owner")
async def copy_projectversion(request):
    """
    Clone a project version.

    ---
    description: Clone a project version.
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          description: Project version data
          required: true
          schema:
              type: object
              properties:
                  name:
                      type: string
                      description: Name of the new projectversion
                  description:
                      type: string
                      description: description of the projectversion
                  dependency_policy:
                      type: string
                      description: Dependency policy
                  basemirror:
                      type: string
                      description: Basemirror
                  baseproject:
                      type: string
                      description: Baseproject
                  architectures:
                      type: array
                      items:
                        type: string
                      description: E.g. i386, amd64, arm64, armhf, ...
                  cibuilds:
                      type: boolean
                      description: cibuilds
                  buildlatest:
                      type: boolean
                      description: build latest
<<<<<<< HEAD
                  retention_successful_builds:
                      type: integer
                  retention_failed_builds:
                    type: integer
=======
>>>>>>> swagger: fix API documentation
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: No valid name for the projectversion received
    """
    db = request.cirrina.db_session
    params = await request.json()
    new_version = params.get("name")
    description = params.get("description")
    dependency_policy = params.get("dependency_policy")
    basemirror = params.get("basemirror")
    baseproject = params.get("baseproject")
    architectures = params.get("architectures", None)
    cibuilds = params.get("cibuilds", False)
    buildlatest = params.get("buildlatest", False)
    retention_successful_builds = params.get("retention_successful_builds", None)
    retention_failed_builds = params.get("retention_failed_builds", None)

    min_successful_builds = 1
    max_successful_builds = 5
    min_failed_builds = 7

    if (
        retention_successful_builds is not None
        and (
            not isinstance(retention_successful_builds, int)
            or retention_successful_builds <min_successful_builds
            or retention_successful_builds > max_successful_builds
        )
    ):
        return ErrorResponse(
            400, f"Invalid retention_successful_builds. It should be an integer between {min_successful_builds} and {max_successful_builds}.",
        )
    if (
        retention_failed_builds is not None
        and (
            not isinstance(retention_failed_builds, int)
            or retention_failed_builds < min_failed_builds
        )
    ):
        return ErrorResponse(
            400, f"Invalid retention_failed_builds. It should be an integer greater than or equal to {min_failed_builds}."
        )

    if not new_version:
        return ErrorResponse(400, "No valid name for the projectversion received")
    if not is_name_valid(new_version):
        return ErrorResponse(400, "Invalid project name!")
    if basemirror and not ("/" in basemirror):
        return ErrorResponse(400, "No valid basemirror received (format: 'name/version')")
    if baseproject and not ("/" in baseproject):
        return ErrorResponse(400, "No valid baseproject received (format: 'name/version')")
    if not architectures:
        return ErrorResponse(400, "No architecture received")
    if len(architectures) == 0:
        return ErrorResponse(400, "No architecture received")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(404, "Projectversion not found")

    if db.query(ProjectVersion).join(Project).filter(
                func.lower(ProjectVersion.name) == new_version.lower(),
                Project.id == projectversion.project_id).first():
        return ErrorResponse(400, "Projectversion already exists.")

    bm = None
    pv = None
    if baseproject:
        baseproject_name, baseproject_version = baseproject.split("/")
        pv = db.query(ProjectVersion).join(Project).filter(
                Project.is_basemirror.is_(False),
                func.lower(Project.name) == baseproject_name.lower(),
                func.lower(ProjectVersion.name) == baseproject_version.lower()).first()
        if not pv:
            return ErrorResponse(400, "Base project not found: {}/{}".format(baseproject_name, baseproject_version))
        bm = pv.basemirror
    else:
        basemirror_name, basemirror_version = basemirror.split("/")
        bm = db.query(ProjectVersion).join(Project).filter(
                Project.is_basemirror.is_(True),
                func.lower(Project.name) == basemirror_name.lower(),
                func.lower(ProjectVersion.name) == basemirror_version.lower()).first()
        if not bm:
            return ErrorResponse(400, "Base mirror not found: {}/{}".format(basemirror_name, basemirror_version))

    new_projectversion = projectversion.copy(db, new_version, description, dependency_policy, bm.id, architectures, cibuilds, retention_successful_builds, retention_failed_builds)

    if baseproject:
        pdep = ProjectVersionDependency(
                projectversion_id=new_projectversion.id,
                dependency_id=pv.id,
                use_cibuilds=False)
        db.add(pdep)
        db.commit()

    trigger_builds = []
    if buildlatest:
        latest_builds = latest_project_builds(db, projectversion.id)
        for latest_build in latest_builds:
            topbuild = latest_build.parent.parent
            # if topbuild.buildstate != "successful":
            #     continue
            if topbuild.sourcerepository is None:
                continue
            build = Build(
                version=topbuild.version,
                git_ref=topbuild.git_ref,
                ci_branch=topbuild.ci_branch,
                is_ci=False,
                sourcename=topbuild.sourcename,
                buildstate="new",
                buildtype="build",
                sourcerepository=topbuild.sourcerepository,
                maintainer=None,
            )

            db.add(build)
            db.commit()
            await build.build_added()
            trigger_builds.append(build.id)

    copy_build = Build(
        version=new_version,
        git_ref=None,
        ci_branch=None,
        is_ci=False,
        sourcename=f"copy {projectversion.project.name}/{projectversion.name}",
        buildstate="new",
        buildtype="copy_projectversion",
        sourcerepository=None,
        maintainer=None,
    )
    db.add(copy_build)
    db.commit()
    await copy_build.build_added()
    await copy_build.set_building()
    db.commit()

    await enqueue_aptly({"init_repository": [
                bm.project.name,
                bm.name,
                projectversion.project.name,
                new_version,
                architectures,
                trigger_builds,
                copy_build.id]})

    data = {"build_id": copy_build.id, "rebuild_ids": trigger_builds}
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/lock")
@req_role("owner")
async def lock_projectversion(request):
    """
    Lock a project version.

    ---
    description: Clone a project version.
    tags:
        - Projects
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.basemirror.external_repo:
        return ErrorResponse(400, "Projectversion is based on external mirror")

    return do_lock(request, projectversion.id)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/unlock")
@req_role("owner")
async def unlock_projectversion(request):
    """
    Unlock a project version.

    ---
    description: Unlock a project version.
    tags:
        - Projects
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.basemirror.external_repo:
        return ErrorResponse(400, "Projectversion is based on external mirror")

    return do_unlock(request, projectversion.id)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/overlay")
@req_role("owner")
async def overlay_projectversion(request):
    """
    Overlay a project version.

    ---
    description: Overlay a project version.
    tags:
        - Projects
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: name
          in: body
          description: Name of project version
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
            description: Invalid project name
    """
    params = await request.json()

    name = params.get("name")
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    return await do_overlay(request, projectversion.id, name)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/snapshot")
@req_role("owner")
async def snapshot_projectversion(request):
    """
    Create a snapshot of a project version

    ---
    description: Create a snapshot of a project version.
    tags:
        - Projects
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: name
          in: body
          description: Name of project version snapshot
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
            description: Invalid project name
    """
    params = await request.json()

    name = params.get("name")
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.basemirror.external_repo:
        return ErrorResponse(400, "Projectversion is based on external mirror")
    if projectversion.projectversiontype == 'snapshot':
        return ErrorResponse(400, "Cannot snapshot snapshots")

    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    db = request.cirrina.db_session
    if db.query(ProjectVersion).join(Project).filter(
            func.lower(ProjectVersion.name) == name.lower(),
            Project.id == projectversion.project_id).first():
        return ErrorResponse(400, "Projectversion '%s' already exists" % name)

    # check dependencies are locked
    for dep in projectversion.dependencies:
        if not dep.is_locked:
            return ErrorResponse(400, "Dependency '%s/%s' is not locked" % (dep.project.name, dep.name))

    # get top level build for each latest build
    latest_builds = latest_project_builds(db, projectversion.id)
    latest_debbuilds_ids = []
    for latest_build in latest_builds:
        # if latest_build.buildstate != "successful":
        #     return ErrorResponse(400, "Not all latest builds are successful: %d (%s)" % (latest_build.id,
        #                                                                                  latest_build.sourcename))
        for debbuild in latest_build.parent.children:
            if debbuild.projectversion_id != projectversion.id:
                continue
            if not debbuild.debianpackages:
                return ErrorResponse(400, "No debian packages found for %s/%s" % (debbuild.sourcename, debbuild.version))
            latest_debbuilds_ids.append(debbuild.id)

    if len(latest_debbuilds_ids) == 0:
        return ErrorResponse(400, "No snapshotable builds found")

    new_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        dependencies=projectversion.dependencies,   # FIXME: use_cibuilds not included via relationship
        mirror_architectures=projectversion.mirror_architectures,
        basemirror_id=projectversion.basemirror_id,
        sourcerepositories=projectversion.sourcerepositories,
        ci_builds_enabled=False,
        is_locked=True,
        projectversiontype="snapshot",
        baseprojectversion_id=projectversion.id,
        dependency_policy=projectversion.dependency_policy
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

    await enqueue_aptly(
        {
            "snapshot_repository": [
                projectversion.basemirror.project.name,
                projectversion.basemirror.name,
                projectversion.project.name,
                projectversion.name,
                db2array(projectversion.mirror_architectures),
                new_projectversion.name,
                new_projectversion.id,
                latest_debbuilds_ids
            ]
        }
    )

    return OKResponse({"id": new_projectversion.id, "name": new_projectversion.name})


@app.http_delete("/api2/project/{project_id}/{projectversion_id}")
@req_role("owner")
async def delete_projectversion(request):
    """
    Delete Project Version

    ---
    description: Deletes a project version, including associated builds, repositories and dependencies.
    tags:
        - Projects
    consumes:
        - application/json
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: forceremoval
          in: query
          required: false
          type: boolan
    produces:
        - text/json
    responses:
        "200":
            description: Projectversion deleted successfully.
        "400":
            description: Projectversion not found
    """
    force = request.GET.getone("forceremoval", None)
    force = force == "true"
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    if projectversion.dependents:
        blocking_dependents = []
        for d in projectversion.dependents:
            if not d.is_deleted:
                blocking_dependents.append("{}/{}".format(d.project.name, d.name))
                logger.error("projectversion delete: projectversion_id %d still has dependency %d", projectversion.id, d.id)
        if blocking_dependents:
            return ErrorResponse(400, "Projectversions '{}' are still depending on this version, cannot delete it".format(
                                  ", ".join(blocking_dependents)))

    db = request.cirrina.db_session
    if not force:
        # do not delete PV if builds are running
        debbuilds = db.query(Build).filter(Build.projectversion_id == projectversion.id, Build.buildtype == "deb", or_(
                                           Build.buildstate == "needs_build",
                                           Build.buildstate == "scheduled",
                                           Build.buildstate == "building",
                                           Build.buildstate == "needs_publish",
                                           Build.buildstate == "publishing"
                                           )).first()
        if debbuilds:
            return ErrorResponse(400, "Builds are still depending on this version, cannot delete it")

    # mark as deleted
    projectversion.is_deleted = True
    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False

    delete_build = Build(
        version=projectversion.name,
        git_ref=None,
        ci_branch=None,
        is_ci=False,
        sourcename=f"delete {projectversion.project.name}/{projectversion.name}",
        buildstate="new",
        buildtype="delete_projectversion",
        sourcerepository=None,
        maintainer=None,
    )
    db.add(delete_build)

    await delete_build.build_added()
    await delete_build.set_building()
    db.commit()

    await enqueue_aptly({"delete_repository": [projectversion.id, delete_build.id]})

    data = {"build_id": delete_build.id}
    return OKResponse(data)


@app.http_delete("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
@req_role(["member", "owner"])
async def remove_repository2(request):
    """
    Remove a sourcerepositories from a projectversion.

    ---
    description: Remove a sourcerepositories from a projectversion.
    tags:
        - ProjectVersions
    consumes:
        - application/json
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
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
            description: Sourcerepository removed from projectversion
        "400":
            description: Projectversion not found
    """
    db = request.cirrina.db_session
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")
    try:
        sourcerepository_id = int(request.match_info["sourcerepository_id"])
    except Exception:
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


@app.http_get("/api2/project/{project_name}/{project_version}/aptsources")
async def get_apt_sources2(request):
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
          type: string
        - name: project_version
          in: path
          required: true
          type: string
        - name: unstable
          in: query
          required: false
          type: boolean
          description: Include unstable APT sources. Default is false.
        - name: internal
          in: query
          required: false
          type: boolean
          description: Include internal APT sources. Default is false.
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    db = request.cirrina.db_session
    unstable = request.GET.getone("unstable", False)
    if unstable == "true":
        unstable = True
    internal = request.GET.getone("internal", False)
    if internal == "true":
        internal = True

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "projectversion not found")

    deps = [(projectversion.id, projectversion.ci_builds_enabled)]
    deps += get_projectversion_deps(projectversion.id, db)

    cfg = Configuration()
    apt_url = None
    if not internal:
        apt_url = cfg.aptly.get("apt_url_public")
    if not apt_url:
        apt_url = cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources_list = "# APT Sources for project {0} {1}\n".format(projectversion.project.name, projectversion.name)
    sources_list += "# GPG-Key: {0}/{1}\n".format(apt_url, keyfile)
    if not projectversion.project.is_basemirror and projectversion.basemirror:
        sources_list += "\n# Base Mirror\n"
        sources_list += "{}\n".format(projectversion.basemirror.get_apt_repo(internal=internal))

    sources_list += "\n# Project Sources\n"
    for d in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d[0]).first()
        if not dep:
            logger.error("projectsources: projecversion %d not found", d[0])
        sources_list += "{}\n".format(dep.get_apt_repo(internal=internal))
        # ci builds requested & use ci builds from this dep & dep has ci builds
        if unstable and d[1] and dep.ci_builds_enabled:
            sources_list += "{}\n".format(dep.get_apt_repo(dist="unstable", internal=internal))

    return web.Response(status=200, text=sources_list)


@app.http_get("/api2/project/{project_id}/{projectversion_id}/dependents")
@app.authenticated
async def get_projectversion_dependents(request):
    """
    Returns a list of projectversions.

    ---
    description: Returns a list of projectversions.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: project_id
          in: path
          required: true
          type: integer
        - name: candidates
          in: query
          required: false
          type: boolean
        - name: q
          in: query
          required: false
          type: string
          description: Filter query
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

    # get existing dependents
    deps = projectversion.dependents
    dep_ids = []
    for d in deps:
        dep_ids.append(d.id)

    if candidates:  # return candidate dependents
        results = []
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
                                                                                func.lower(Project.name),
                                                                                func.lower(ProjectVersion.name))
        if filter_name:
            cands = cands.filter(ProjectVersion.fullname.ilike("%{}%".format(filter_name)))

        for cand in cands.all():
            results.append(cand.data())

        data = {"total_result_count": len(results), "results": results}
        return OKResponse(data)

    # return existing dependents
    results = []
    for d in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d.id)
        if filter_name:
            dep = dep.filter(ProjectVersion.fullname.ilike("%{}%".format(filter_name)))
        dep = dep.first()
        if dep:
            data = dep.data()
            results.append(data)

    # FIXME paginate ??
    data = {"total_result_count": len(results), "results": results}
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/extbuild")
@req_role("owner")
async def external_build_upload(request):
    """
    Initiates an external build upload process.

    ---
    description: Initiates an external build upload process.
    tags:
        - Projects
    consumes:
        - application/json
        parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: project_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "201":
            description: External build upload initiated successfully.
        "500":
            description: Projectversion not found
    """
    db = request.cirrina.db_session

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Cannot add dependencies to project which is a mirror")
    if projectversion.is_locked:
        return ErrorResponse(400, "Cannot add dependencies on a locked projectversion")

    # TODO
    # check extbuilds allowed

    maintenance_mode = False
    query = "SELECT value from metadata where name = :key"
    result = db.execute(query, {"key": "maintenance_mode"})
    for value in result:
        if value[0] == "true":
            maintenance_mode = True
        break
    if maintenance_mode:
        return web.Response(status=503, text="Maintenance Mode")

    # create builds
    build = Build(
        version=None,
        git_ref=None,
        ci_branch=None,
        is_ci=False,
        sourcename="external build upload",
        buildstate="new",
        buildtype="build",
        sourcerepository=None,
        maintainer=None,
        projectversion_id=projectversion.id,
    )

    db.add(build)
    db.commit()
    await build.logtitle("External Build Upload")
    await build.build_added()

    srcbuild = Build(
        version="unknown",
        git_ref=None,
        ci_branch=None,
        is_ci=False,
        sourcename="external build upload",
        buildstate="new",
        buildtype="source",
        parent_id=build.id,
        sourcerepository=None,
        maintainer=None,
        projectversion_id=projectversion.id,
        projectversions=array2db([str(projectversion.id)])
    )

    db.add(srcbuild)
    db.commit()
    await srcbuild.build_added()

    # loop = asyncio.get_event_loop()
    # loop.create_task(
    await finalize_extbuild(build.id, projectversion.id, srcbuild.id, request.multipart)
    # )
    return OKResponse({"build_id": build.id}, status=201)


async def finalize_extbuild(build_id, projectversion_id, srcbuild_id, multipart):
    buildout_path = Path(Configuration().working_dir) / "buildout"
    build_version = None
    sourcename = None
    source_pkg = None
    dsc_file = None
    source_upload = False
    has_changes_file = False
    has_buildinfo_file = False
    changes_file = None

    async def write_part(build_id, part):
        filename = part.filename.replace("/", "")  # no paths separators allowed
        dir_path = buildout_path / str(build_id)
        if not dir_path.is_dir():
            dir_path.mkdir(parents=True)
        async with AIOFile("%s/%s" % (dir_path, filename), "xb") as afp:
            writer = Writer(afp)
            while True:  # FIXME: timeout
                # FIXME: might not return, timeout and cancel
                chunk = await part.read_chunk()  # 8192 bytes by default.
                if not chunk:
                    break
                await writer(chunk)

    async def get_debbuild(arch, version, srcbuild_id, projectversion_id):
        # create deb builds per arch
        if arch == "all":
            arch = "amd64"  # FIXME: should be arch from project
        with Session() as db:
            debbuild = session.query(Build).filter(Build.version == version,
                                                   Build.buildstate == "new",
                                                   Build.buildtype == "deb",
                                                   Build.parent_id == srcbuild_id,
                                                   Build.projectversion_id == projectversion_id,
                                                   Build.architecture == arch).first()
            if not debbuild:
                debbuild = Build(
                    version=version,
                    git_ref=None,
                    ci_branch=None,
                    is_ci=False,
                    sourcename="external build upload",
                    buildstate="new",
                    buildtype="deb",
                    parent_id=srcbuild_id,
                    sourcerepository=None,
                    maintainer=None,
                    projectversion_id=projectversion_id,
                    architecture=arch
                )

                db.add(debbuild)
                db.commit()
                await debbuild.build_added()
            return debbuild.id

    with Session() as session:
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            await build.log("E: build not found: '%d'\n" % build_id)
            return False

        await build.log("I: Receiving uploaded files\n")

    logs = []
    try:
        reader = await multipart()
        async for part in reader:
            filename = part.filename.replace("/", "")  # sanitize
            filename = filename.replace("$", "")
            filename = filename.replace("`", "")
            filename = filename.replace("'", "")
            filename = filename.replace("\"", "")
            filename = filename.replace("\\", "")

            await build.log(" - %s\n" % filename)

            destbuild_id = None

            arch = None
            pkgname = None
            version = None
            if filename.endswith(".deb"):
                s = filename[:-4].split("_", 3)
                if len(s) != 3:
                    logs.append("W: invalid filename: '%s'\n" % filename)
                    continue
                pkgname, version, arch = s
                destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)

            elif filename.endswith(".changes"):
                s = filename[:-4].split("_", 3)
                if len(s) != 3:
                    logs.append("W: invalid filename: '%s'\n" % filename)
                    continue
                pkgname, version, arch = s
                arch = arch.split(".")[0]
                has_changes_file = True
                if not sourcename:
                    sourcename = pkgname
                destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)
                changes_file = buildout_path / str(destbuild_id) / filename

            elif filename.endswith(".buildinfo"):
                s = filename[:-4].split("_", 3)
                if len(s) != 3:
                    logs.append("W: invalid filename: '%s'\n" % filename)
                    continue
                pkgname, version, arch = s
                arch = arch.split(".")[0]
                has_buildinfo_file = True
                if not sourcename:
                    sourcename = pkgname
                destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)

            elif filename.endswith(".dsc"):
                s = filename[:-4].split("_", 2)
                if len(s) != 2:
                    logs.append("W: invalid filename: '%s'\n" % filename)
                    continue
                dsc_file = filename
                pkgname, version = s
                destbuild_id = srcbuild_id
                if not sourcename:
                    sourcename = pkgname

            elif filename.endswith(".tar.gz") or filename.endswith(".tar.xz"):
                if source_upload:
                    logs.append("W: only one source package allowed: '%s'\n" % filename)
                    continue
                source_pkg = filename
                s = filename[:-7].split("_", 2)
                if len(s) == 2:
                    pkgname, version = s
                    destbuild_id = srcbuild_id
                    source_upload = True
                    if not sourcename:
                        sourcename = pkgname

            else:
                logs.append("W: ignoring unknown file type: '%s'\n" % filename)
                continue

            if not build_version:
                build_version = version
            elif version != build_version:
                # FIXME: cleanup saved files
                logs.append("E: version mismatch in uploaded files: '%s'\n" % version)
                return False

            # FIXME: check arch in projectversion
            await write_part(destbuild_id, part)
    except Exception as exc:
        logs.append("E: error uploading file")
        logger.exception(exc)
        return False

    with Session() as session:
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            await build.log("E: build not found: '%d'\n" % build_id)
            return False

        srcbuild = session.query(Build).filter(Build.id == srcbuild_id).first()
        if not srcbuild:
            await build.log("E: build not found: '%d'\n" % srcbuild_id)
            return False

        debbuilds = session.query(Build).filter(Build.parent_id == srcbuild_id).all()
        if not debbuilds:
            await build.log("E: no deb builds found for source build: '%d'\n" % srcbuild_id)
            return False

        for log in logs:
            await build.log(log)

        await build.log("I: Verifying uploaded files...\n")

        if not has_changes_file:
            errmsg = "Missing *.changes file"
            await build.log("E: %s\n" % errmsg)
            await build.set_failed()
            await srcbuild.set_failed()
            for debbuild in debbuilds:
                await debbuild.set_failed()
            session.commit()
            return False

        if not has_buildinfo_file:
            errmsg = "Missing *.buildinfo file"
            await build.log("E: %s\n" % errmsg)
            await build.set_failed()
            await srcbuild.set_failed()
            for debbuild in debbuilds:
                await debbuild.set_failed()
            session.commit()
            return False

        await build.log("I: Found external build: %s/%s\n" % (sourcename, build_version))

        # Fix changes file for source uploads
        if source_upload:
            # remove dsc entry from changes file, as it is signed in the source upload
            async def outh(line):
                if len(line.strip()) != 0:
                    logger.info(line)

            d = dsc_file.replace(".", "\\.")
            s = source_pkg.replace(".", "\\.")
            cmd = f"sed -i -e '/{d}$/d' -e '/{s}$/d' {changes_file}"
            process = Launchy(cmd, outh, outh)
            await process.launch()
            ret = await process.wait()
            if ret != 0:
                logger.error("build upload: patching changes file failed")

        build.sourcename = sourcename
        srcbuild.sourcename = sourcename
        for debbuild in debbuilds:
            debbuild.sourcename = sourcename
        build.version = build_version
        srcbuild.version = build_version
        session.commit()

        # check if version already existsrun
        existing_build = session.query(Build).filter(Build.buildtype == "build",
                                                     Build.sourcerepository_id.is_(None),
                                                     Build.projectversion_id == projectversion_id,
                                                     Build.buildstate == "successful",  # FIXME: or new, building, publishing
                                                     Build.is_deleted.is_(False),
                                                     Build.sourcename == sourcename,
                                                     Build.version == build_version).first()
        if existing_build:
            errmsg = "build for %s/%s already exists" % (sourcename, version)
            await build.log("E: %s\n" % errmsg)
            await build.set_failed()
            await build.logtitle("Done", no_footer_newline=True, no_header_newline=False)
            await srcbuild.set_failed()
            for debbuild in debbuilds:
                await debbuild.set_failed()
            session.commit()
            return False

        await build.set_building()
        session.commit()

        # publish source package
        await srcbuild.logtitle("External Source Upload")
        if source_upload:
            await srcbuild.set_needs_publish()
            session.commit()
            await srcbuild.log("I: verifying source package\n")
            await enqueue_aptly({"src_publish": [srcbuild.id]})
        else:
            await srcbuild.log("W: no source package to publish\n")
            await srcbuild.set_nothing_done()
            session.commit()

        # publish debian packages
        for debbuild in debbuilds:
            await debbuild.logtitle("External Debian Package Upload")
            await debbuild.set_needs_publish()
            session.commit()
            await debbuild.log("I: verifying debian packages\n")
            await enqueue_aptly({"publish": [debbuild.id]})

    return True


@app.http_delete("/api2/project/{project_id}/{projectversion_id}/build/{build_id}")
@req_role("owner")
async def delete_projectversion_build(request):
    """
    Delete Project Version Build

    ---
    description: Deletes a specific build associated with a project version.
    tags:
        - Projects
    consumes:
        - application/json
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: build_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: Build is being deleted
        "400":
            description: Projectversion not found
    """
    db = request.cirrina.db_session

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.project.is_mirror:
        return ErrorResponse(400, "Cannot delete build on project which is a mirror")
    if projectversion.is_locked:
        return ErrorResponse(400, "Cannot delete build on a locked projectversion")

    try:
        build_id = int(request.match_info["build_id"])
    except Exception:
        return ErrorResponse(400, "No valid build_id received")

    # copied from api2/build.py
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found" % build_id)
        return ErrorResponse(404, "Build not found")

    topbuild = None
    builds = []
    if build.buildtype == "deb":
        topbuild = build.parent.parent
        builds.extend([build.parent, build.parent.parent])
        for b in build.parent.children:
            builds.append(b)
    elif build.buildtype == "source":
        topbuild = build.parent
        builds.extend([build, build.parent])
        for b in build.children:
            builds.append(b)
    elif build.buildtype == "build":
        topbuild = build
        builds.append(build)
        for b in build.children:
            builds.append(b)
            for c in b.children:
                builds.append(c)

    if not topbuild:
        return ErrorResponse(400, "Build of type %s cannot be deleted" % build.buildtype)

    for srcbuild in topbuild.children:
        for debbuild in srcbuild.children:
            # FIXME: check if this project
            if debbuild.projectversion.id != projectversion.id:
                return ErrorResponse(400, "Builds for multiple projectversion cannot be deleted")

            if debbuild.projectversion and debbuild.projectversion.is_locked:
                return ErrorResponse(400, "Build from locked projectversion cannot be deleted")

            if debbuild.buildstate == "scheduled" or \
               debbuild.buildstate == "building" or \
               debbuild.buildstate == "needs_publish" or \
               debbuild.buildstate == "publishing":
                return ErrorResponse(400, "Build in state %s cannot be deleted" % debbuild.buildstate)

    for b in builds:
        b.is_deleted = True
    db.commit()

    await enqueue_aptly({"delete_build": [topbuild.id]})
    return OKResponse("Build is being deleted")

@app.http_get("/api2/cleanup")
async def get_cleanup(request):

    db = request.cirrina.db_session

    cleanup_active_metadata = db.query(MetaData).filter_by(name='cleanup_active').first()
    cleanup_time_metadata = db.query(MetaData).filter_by(name='cleanup_time').first()
    cleanup_weekdays_metadata = db.query(MetaData).filter_by(name='cleanup_weekdays').first()

    logger.info(cleanup_active_metadata)
    logger.info(cleanup_time_metadata)
    logger.info(cleanup_weekdays_metadata)

    cleanup_active = cleanup_active_metadata.value if cleanup_active_metadata else None
    cleanup_time = cleanup_time_metadata.value if cleanup_time_metadata else None
    cleanup_weekdays = cleanup_weekdays_metadata.value.split(',') if cleanup_weekdays_metadata else None

    logger.info(cleanup_active)
    logger.info(cleanup_time)
    logger.info(cleanup_weekdays)

    data = {
    'cleanup_active': cleanup_active,
    'cleanup_time': cleanup_time,
    'cleanup_weekdays': cleanup_weekdays
    }

    logger.info(data)
    db.close()

    return OKResponse(data)

@app.http_put("/api2/cleanup")
async def edit_cleanup(request):

    params = await request.json()
    cleanup_active = params.get("cleanup_active")
    cleanup_weekdays = params.get("cleanup_weekdays")
    cleanup_time = params.get("cleanup_time")

    db = request.cirrina.db_session

    existing_active_metadata = db.query(MetaData).filter_by(name='cleanup_active').first()
    if existing_active_metadata:
        existing_active_metadata.value = str(cleanup_active)
    else:
        db.add(MetaData(name='cleanup_active', value=str(cleanup_active)))

    existing_weekdays_metadata = db.query(MetaData).filter_by(name='cleanup_weekdays').first()
    if existing_weekdays_metadata:
        existing_weekdays_metadata.value = cleanup_weekdays
    else:
        db.add(MetaData(name='cleanup_weekdays', value=cleanup_weekdays))

    existing_time_metadata = db.query(MetaData).filter_by(name='cleanup_time').first()
    if existing_time_metadata:
        existing_time_metadata.value = cleanup_time
    else:
        db.add(MetaData(name='cleanup_time', value=cleanup_time))

    db.commit()

    return OKResponse("Cleanup job is being configured")


@app.http_post("/api2/project/{project_id}/{projectversion_id}/s3")
@req_admin
async def publish_s3(request):
    """
    Configures publishing to S3

    ---
    description: Configures publishing to S3
    tags:
        - Projects
    consumes:
        - application/json
        parameters:
        - name: projectversion_id
          in: path
          required: true
          type: string
        - name: project_id
          in: path
          required: true
          type: string
    produces:
        - text/json
    responses:
        "201":
            description: Success
        "400":
            description: Projectversion not found
    """
    db = request.cirrina.db_session

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    maintenance_mode = False
    query = "SELECT value from metadata where name = :key"
    result = db.execute(query, {"key": "maintenance_mode"})
    for value in result:
        if value[0] == "true":
            maintenance_mode = True
        break
    if maintenance_mode:
        return web.Response(status=503, text="Maintenance Mode")

    params = await request.json()
    publish_s3 = params.get("publish_s3", False)
    s3_endpoint = params.get("s3_endpoint")
    s3_path = params.get("s3_path")

    old_publish = projectversion.publish_s3
    old_endpoint = projectversion.s3_endpoint
    old_path = projectversion.s3_path

    projectversion.publish_s3 = publish_s3
    projectversion.s3_endpoint = s3_endpoint
    projectversion.s3_path = s3_path

    db.commit()

    if publish_s3 and not old_publish:  # create publish to s3
        await enqueue_aptly({"publish_s3": [projectversion.id]})
    elif not publish_s3 and old_publish:  # delete s3 publish
        await enqueue_aptly({"remove_s3": [projectversion.id, old_endpoint, old_path]})
    if publish_s3 and old_publish:  # stay enabled
        if old_endpoint != s3_endpoint or old_path != s3_path:  # something changed
            await enqueue_aptly({"remove_s3": [projectversion.id, old_endpoint, old_path]})
            await enqueue_aptly({"publish_s3": [projectversion.id]})

    return OKResponse(status=201)


@app.http_get("/api2/s3")
async def s3_endpoints(request):
    """
    ---
    description: Lists S3 Endpoints
    tags:
        - Projects
    produces:
        - text/json
    responses:
        "200":
            description: Success
    """
    aptly = get_aptly_connection()
    data = await aptly.s3_endpoints()
    return OKResponse(data)
