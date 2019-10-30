"""
Provides functions to interact with the ProjectVersion
database model.
"""
import logging
from aiohttp import web
import uuid

from molior.model.projectversion import ProjectVersion, get_projectversion_deps
from molior.model.project import Project
from molior.model.build import Build
from molior.model.buildtask import BuildTask
from molior.model.buildvariant import BuildVariant
from molior.model.sourcerepository import SourceRepository
from molior.model.sourepprover import SouRepProVer
from molior.model.buildconfiguration import BuildConfiguration
from molior.molior.notifier import build_added

from .app import app
from .inputparser import parse_int
from .helper.buildvariant import get_buildvariants
from .helper.validator import is_name_valid

logger = logging.getLogger("molior-web")  # pylint: disable=invalid-name


def get_projectversion_deps_manually(projectversion, to_dict=True):
    """
    Returns all dependencies of given projectversion (recursive).

    Args:
        projectversion (ProjectVersion): The ProjectVersion model instance.
        to_dict (bool): If True output will be dict.
    """

    deps = []

    def get_deps(projectv):
        """
        Returns a list of dependencies
        of the given projectversion.
        Recursively calls this function until
        all subdependencies are appended to
        the "deps" list.

        Args:
            projectv (ProjectVersion): The ProjectVersion model instance.
        """
        if not projectv:
            return

        if projectv not in deps and projectversion.id != projectv.id:
            dep = projectversion_to_dict(projectv) if to_dict else projectv
            if dep not in deps:
                deps.append(dep)

        for dep in projectv.dependencies:
            get_deps(dep)

    get_deps(projectversion)

    return deps


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
    archs = []
    if projectversion.project.is_mirror and projectversion.mirror_architectures:
        archs = projectversion.mirror_architectures[1:-1].split(",")

    projectversion_dict = {
        "id": projectversion.id,
        "name": projectversion.name,
        "project": {
            "name": projectversion.project.name,
            "id": projectversion.project.id,
            "description": projectversion.project.description,
            "is_mirror": projectversion.project.is_mirror,
            "is_basemirror": projectversion.project.is_basemirror,
        },
        "apt_url": projectversion.get_apt_repo(),
        "is_locked": projectversion.is_locked,
        "ci_builds_enabled": projectversion.ci_builds_enabled,
        "mirror_state": projectversion.mirror_state,
        "mirror_architectures": archs,
    }

    return projectversion_dict


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
    project_id = request.GET.getone("exclude_id", None)
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    dependant_id = request.GET.getone("dependant_id", None)

    query = (
        request.cirrina.db_session.query(ProjectVersion)
        .join(Project)
        .filter(ProjectVersion.is_deleted == False)  # noqa: E712
    )

    projectversion_id = parse_int(project_id)
    if projectversion_id:
        query = query.filter(Project.id != project_id)

    if basemirror_id:
        query = query.filter(ProjectVersion.buildvariants.any(BuildVariant.base_mirror_id == basemirror_id))
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")  # pylint: disable=no-member

    if dependant_id:
        p_version = (
            request.cirrina.db_session.query(
                ProjectVersion
            )  # pylint: disable=no-member
            .filter(ProjectVersion.id == dependant_id)
            .first()
        )
        projectversions = []
        if p_version:
            projectversions = [p_version.buildvariants[0].base_mirror]
        nb_projectversions = len(projectversions)
    else:
        query = query.order_by(Project.name, ProjectVersion.name)
        projectversions = query.all()
        nb_projectversions = query.count()

    results = []

    for projectversion in projectversions:
        projectversion_dict = projectversion_to_dict(projectversion)
        projectversion_dict["dependencies"] = get_projectversion_deps_manually(projectversion)
        results.append(projectversion_dict)

    data = {"total_result_count": nb_projectversions, "results": results}

    return web.json_response(data)


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
    projectversion_id = request.match_info["projectversion_id"]
    try:
        projectversion_id = int(projectversion_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for projectversion_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)  # pylint: disable=no-member
        .first()
    )

    if not projectversion:
        return web.Response(status=400, text="Projectversion %d not found" % projectversion_id)

    if projectversion.is_deleted:
        return web.Response(status=404, text="Projectversion {} deleted".format(projectversion_id))

    projectversion_dict = projectversion_to_dict(projectversion)
    projectversion_dict["dependencies"] = get_projectversion_deps_manually(projectversion)

    projectversion_dict["basemirror_url"] = str()
    if projectversion.buildvariants:
        projectversion_dict["basemirror_url"] = projectversion.buildvariants[0].base_mirror.get_apt_repo()

    return web.json_response(projectversion_dict)


@app.http_post("/api/projects/{project_id}/versions")
@app.req_role("owner")
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
        - name: project_id
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
    project_id = parse_int(request.match_info["project_id"])

    if not project_id:
        return web.Response(status=400, text="No valid project id received")
    if not name:
        return web.Response(status=400, text="No valid name for the projectversion recieived")
    if not basemirror or not ("/" in basemirror):
        return web.Response(status=400, text="No valid basemirror received (format: 'name/version')")
    if not architectures:
        return web.Response(status=400, text='No valid architecture received')

    if not is_name_valid(name):
        return web.Response(status=400, text="Invalid project name!")

    basemirror_name, basemirror_version = basemirror.split("/")
    project = request.cirrina.db_session.query(Project).filter(Project.id == project_id).first()

    if not project:
        return web.Response(status=400, text="Project with id '{}' could not be found".format(project_id))

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .join(Project)
        .filter(ProjectVersion.name == name)
        .filter(Project.id == project.id)
        .first()
    )
    if projectversion:
        return web.Response(status=400, text="Projectversion already exists. {}".format(
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


@app.http_post("/api/projectversions/{projectversion_id}/repositories/{sourcerepository_id}")
@app.req_role(["member", "owner"])
@app.authenticated
async def post_add_repository(request):
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
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                buildvariants:
                    type: array
                    example: [1, 2]
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
    """
    params = await request.json()

    projectversion_id = request.match_info["projectversion_id"]
    sourcerepository_id = request.match_info["sourcerepository_id"]
    buildvariants = params.get("buildvariants", [])

    if not buildvariants:
        return web.Response(status=400, text="No buildvariants recieved.")

    projectversion_id = parse_int(projectversion_id)

    project_v = (
        request.cirrina.db_session.query(ProjectVersion)  # pylint: disable=no-member
        .filter(ProjectVersion.id == projectversion_id)
        .first()
    )

    if not project_v:
        return web.Response(status=400, text="Invalid data received.")

    parsed_id = parse_int(sourcerepository_id)
    if not parsed_id:
        return web.Response(status=400, text="Invalid data received.")

    src_repo = (
        request.cirrina.db_session.query(SourceRepository)  # pylint: disable=no-member
        .filter(SourceRepository.id == parsed_id)
        .first()
    )
    if src_repo not in project_v.sourcerepositories:
        project_v.sourcerepositories.append(src_repo)
        request.cirrina.db_session.commit()  # pylint: disable=no-member

    sourepprover_id = (
        (
            request.cirrina.db_session.query(SouRepProVer)  # pylint: disable=no-member
            .filter(SouRepProVer.c.sourcerepository_id == src_repo.id)
            .filter(SouRepProVer.c.projectversion_id == project_v.id)
        )
        .first()
        .id
    )

    for buildvariant in buildvariants:
        # if just the buildvariant id is given
        if buildvariant.get("id"):
            buildvar_id = parse_int(buildvariant.get("id"))
            buildvar = (
                request.cirrina.db_session.query(
                    BuildVariant
                )  # pylint: disable=no-member
                .filter(BuildVariant.id == buildvar_id)
                .first()
            )
        # if basemirror and architecture is given
        elif buildvariant.get("architecture_id") and buildvariant.get("base_mirror_id"):
            arch_id = parse_int(buildvariant.get("architecture_id"))
            base_mirror_id = parse_int(buildvariant.get("base_mirror_id"))
            buildvar = (
                request.cirrina.db_session.query(BuildVariant)
                .filter(
                    BuildVariant.architecture_id == arch_id
                )  # pylint: disable=no-member
                .filter(BuildVariant.base_mirror_id == base_mirror_id)
                .first()
            )
        else:
            return web.Response(status=400, text="Invalid buildvariants received.")

        buildconf = BuildConfiguration(
            buildvariant=buildvar, sourcerepositoryprojectversion_id=sourepprover_id
        )
        request.cirrina.db_session.add(buildconf)

    request.cirrina.db_session.commit()  # pylint: disable=no-member

    logger.info(
        "SourceRepository '%s' with id '%s' added to ProjectVersion '%s/%s'",
        src_repo.url,
        src_repo.id,
        project_v.project.name,
        project_v.name,
    )

    if src_repo.state == "new":
        build = Build(
            version=None,
            git_ref=None,
            ci_branch=None,
            is_ci=None,
            versiontimestamp=None,
            sourcename=src_repo.name,
            buildstate="new",
            buildtype="build",
            buildconfiguration=None,
            sourcerepository=src_repo,
            maintainer=None,
        )

        request.cirrina.db_session.add(build)
        request.cirrina.db_session.commit()
        await build_added(build)

        token = uuid.uuid4()
        buildtask = BuildTask(build=build, task_id=str(token))
        request.cirrina.db_session.add(buildtask)
        request.cirrina.db_session.commit()

        args = {"clone": [build.id, src_repo.id]}
        await request.cirrina.task_queue.put(args)

    return web.Response(status=200, text="SourceRepository added.")


@app.http_delete(
    "/api/projectversions/{projectversion_id}/repositories/{sourcerepository_id}"
)
@app.req_role(["member", "owner"])
@app.authenticated
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
    projectversion_id = parse_int(request.match_info["projectversion_id"])
    sourcerepository_id = parse_int(request.match_info["sourcerepository_id"])
    projectversion_id = parse_int(projectversion_id)
    if not projectversion_id:
        return web.Response(status=400, text="No valid projectversion_id received")

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)  # pylint: disable=no-member
        .filter(ProjectVersion.id == projectversion_id)
        .first()
    )

    if not projectversion:
        return web.Response(
            status=400,
            text="Projectversion {} could not been found.".format(projectversion_id),
        )

    if not sourcerepository_id:
        return web.Response(status=400, text="No valid sourcerepository_id received")

    sourcerepository = (
        request.cirrina.db_session.query(SourceRepository)
        .filter(SourceRepository.id == sourcerepository_id)
        .first()
    )

    if not sourcerepository:
        return web.Response(status=400, text="Sourcerepository {} could not been found".format(sourcerepository_id))

    # get the association of the projectversion and the sourcerepository
    sourcerepositoryprojectversion = (
        request.cirrina.db_session.query(SouRepProVer)  # pylint: disable=no-member
        .filter(SouRepProVer.c.sourcerepository_id == sourcerepository_id)
        .filter(SouRepProVer.c.projectversion_id == projectversion.id)
    ).first()
    if not sourcerepositoryprojectversion:
        return web.Response(status=400, text="Could not find the sourcerepository for the projectversion")

    buildconfigs = (
        request.cirrina.db_session.query(BuildConfiguration).filter(
            BuildConfiguration.sourcerepositoryprojectversion_id
            == sourcerepositoryprojectversion.id
        )
    ).all()

    buildconfig_ids = [b.id for b in buildconfigs]
    if request.cirrina.db_session.query(Build).filter(Build.buildconfiguration_id.in_(buildconfig_ids)).count() > 0:
        return web.Response(status=400, text="There are already builds belonging to this repository, cannot delete it")

    request.cirrina.db_session.query(BuildConfiguration).filter(
            BuildConfiguration.sourcerepositoryprojectversion_id == sourcerepositoryprojectversion.id).delete()
    projectversion.sourcerepositories.remove(sourcerepository)
    request.cirrina.db_session.commit()

    return web.Response(status=200, text="Sourcerepository removed from projectversion")


@app.http_post("/api/projectversions/{projectversion_id}/clone")
@app.req_role("owner")
@app.authenticated
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
    params = await request.json()

    name = params.get("name")
    projectversion_id = parse_int(request.match_info["projectversion_id"])

    if not projectversion_id:
        return web.Response(status=400, text="No valid project id received")
    if not name:
        return web.Response(
            status=400, text="No valid name for the projectversion recieived"
        )

    if not is_name_valid(name):
        return web.Response(status=400, text="Invalid project name!")

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)
        .first()
    )

    if (
        request.cirrina.db_session.query(ProjectVersion)
        .join(Project)
        .filter(ProjectVersion.name == name)
        .filter(Project.id == projectversion.project_id)
        .first()
    ):
        return web.Response(status=400, text="Projectversion already exists.")

    # remove association from database
    new_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        dependencies=projectversion.dependencies,
        buildvariants=projectversion.buildvariants,
        sourcerepositories=projectversion.sourcerepositories,
        ci_builds_enabled=projectversion.ci_builds_enabled,
    )

    for repo in new_projectversion.sourcerepositories:
        sourepprover_id = (
            (
                request.cirrina.db_session.query(
                    SouRepProVer
                )  # pylint: disable=no-member
                .filter(SouRepProVer.c.sourcerepository_id == repo.id)
                .filter(SouRepProVer.c.projectversion_id == projectversion.id)
            )
            .first()
            .id
        )
        new_sourepprover_id = (
            (
                request.cirrina.db_session.query(
                    SouRepProVer
                )  # pylint: disable=no-member
                .filter(SouRepProVer.c.sourcerepository_id == repo.id)
                .filter(SouRepProVer.c.projectversion_id == new_projectversion.id)
            )
            .first()
            .id
        )
        buildconfs = (
            request.cirrina.db_session.query(BuildConfiguration)
            .filter(
                BuildConfiguration.sourcerepositoryprojectversion_id == sourepprover_id
            )
            .all()
        )
        for buildconf in buildconfs:
            new_buildconf = BuildConfiguration(
                buildvariant=buildconf.buildvariant,
                sourcerepositoryprojectversion_id=new_sourepprover_id,
            )
            request.cirrina.db_session.add(new_buildconf)

    request.cirrina.db_session.add(new_projectversion)
    request.cirrina.db_session.commit()

    basemirror = new_projectversion.buildvariants[0].base_mirror
    architectures = [b.architecture.name for b in new_projectversion.buildvariants]

    await request.cirrina.aptly_queue.put(
        {
            "init_repository": [
                new_projectversion.id,
                basemirror.project.name,
                basemirror.name,
                new_projectversion.project.name,
                new_projectversion.name,
                architectures,
            ]
        }
    )

    return web.json_response(
        {"id": new_projectversion.id, "name": new_projectversion.name}
    )


@app.http_post("/api/projectversions/{projectversion_id}/overlay")
@app.req_role("owner")
@app.authenticated
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
    params = await request.json()

    name = params.get("name")
    projectversion_id = parse_int(request.match_info["projectversion_id"])

    if not projectversion_id:
        return web.Response(status=400, text="No valid project id received")
    if not name:
        return web.Response(
            status=400, text="No valid name for the projectversion recieived"
        )

    if not is_name_valid(name):
        return web.Response(status=400, text="Invalid project name!")

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)
        .first()
    )

    if (
        request.cirrina.db_session.query(ProjectVersion)
        .join(Project)
        .filter(ProjectVersion.name == name)
        .filter(Project.id == projectversion.project_id)
        .first()
    ):
        return web.Response(status=400, text="Projectversion already exists.")

    # remove association from database
    overlay_projectversion = ProjectVersion(
        name=name,
        project=projectversion.project,
        # add the projectversion where the overlay is created from as a dependency
        dependencies=[projectversion],
        buildvariants=projectversion.buildvariants,
    )

    request.cirrina.db_session.add(overlay_projectversion)
    request.cirrina.db_session.commit()

    basemirror = overlay_projectversion.buildvariants[0].base_mirror
    architectures = [b.architecture.name for b in overlay_projectversion.buildvariants]

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

    return web.json_response(
        {"id": overlay_projectversion.id, "name": overlay_projectversion.name}
    )


@app.http_post("/api/projectversions/{projectversion_id}/toggleci")
@app.req_role("owner")
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
    projectversion_id = request.match_info["projectversion_id"]
    try:
        projectversion_id = int(projectversion_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for projectversion_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)  # pylint: disable=no-member
        .first()
    )

    if not projectversion:
        return web.Response(
            text="Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id
            ),
            status=400,
        )

    projectversion.ci_builds_enabled = not projectversion.ci_builds_enabled
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    result = "enabled" if projectversion.ci_builds_enabled else "disabled"

    logger.info(
        "continuous integration builds %s on ProjectVersion '%s/%s'",
        result,
        projectversion.project.name,
        projectversion.name,
    )

    return web.Response(text="Ci builds are now {}.".format(result), status=200)


@app.http_post("/api/projectversions/{projectversion_id}/lock")
@app.req_role("owner")
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
    projectversion_id = request.match_info["projectversion_id"]
    try:
        projectversion_id = int(projectversion_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for projectversion_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)  # pylint: disable=no-member
        .first()
    )

    if not projectversion:
        return web.Response(
            text="Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id
            ),
            status=400,
        )

    deps = get_projectversion_deps_manually(projectversion, to_dict=False)
    for dep in deps:
        if not dep.is_locked:
            return web.Response(
                text="Dependencies of given projectversion must be locked", status=400
            )

    projectversion.is_locked = True
    projectversion.ci_builds_enabled = False
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    logger.info(
        "ProjectVersion '%s/%s' locked",
        projectversion.project.name,
        projectversion.name,
    )

    return web.Response(text="Locked Project Version", status=200)


@app.http_put("/api/projectversions/{projectversion_id}/mark-delete")
@app.req_role("owner")
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
    projectversion_id = request.match_info["projectversion_id"]
    try:
        projectversion_id = int(projectversion_id)
    except (ValueError, TypeError):
        logger.error(
            "projectversion mark delete: invalid projectversion_id %s",
            projectversion_id,
        )
        return web.Response(text="invalid projectversion_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)  # pylint: disable=no-member
        .first()
    )

    if not projectversion:
        logger.error(
            "projectversion mark delete: projectversion_id %d not found",
            projectversion_id,
        )
        return web.Response(
            text="Projectversion#{projectversion_id} not found".format(
                projectversion_id=projectversion_id
            ),
            status=400,
        )

    if projectversion.dependents:
        blocking_dependants = []
        for d in projectversion.dependents:
            if not d.is_deleted:
                blocking_dependants.append("{}/{}".format(d.project.name, d.name))
        if blocking_dependants:
            logger.error(
                "projectversion mark delete: projectversion_id %d still has dependency %d",
                projectversion_id,
                d.id,
            )
            return web.Response(
                text="Projectversions '{}' are still depending on this version, you can not delete it!".format(
                    ", ".join(blocking_dependants)
                ),
                status=400,
            )

    base_mirror = projectversion.buildvariants[0].base_mirror
    base_mirror_name = base_mirror.project.name
    base_mirror_version = base_mirror.name

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
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    logger.info(
        "ProjectVersion '%s/%s' deleted",
        projectversion.project.name,
        projectversion.name,
    )

    return web.Response(text="Deleted Project Version", status=200)


@app.http_delete("/api/projectversions/{projectversion_id}/dependency")
@app.req_role("owner")
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
    params = await request.json()

    projectversion_id = parse_int(request.match_info["projectversion_id"])
    if not projectversion_id:
        return web.Response(text="Incorrect value for projectversion_id", status=400)

    dependency_id = parse_int(params.get("dependency_id"))
    if not dependency_id:
        return web.Response(text="Incorrect value for dependency_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)
        .first()
    )

    if not projectversion:
        return web.Response(
            text="Could not find projectversion with id: {}".format(projectversion_id),
            status=400,
        )

    if projectversion.is_locked:
        return web.Response(
            text="You can not delete dependencies on a locked projectversion!",
            status=400,
        )

    dependency = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == dependency_id)
        .first()
    )

    if not dependency:
        return web.Response(
            text="Could not find projectversion dependency with id: {}".format(
                dependency_id
            ),
            status=400,
        )

    projectversion.dependencies.remove(dependency)

    pv_name = "{}/{}".format(projectversion.project.name, projectversion.name)
    dep_name = "{}/{}".format(dependency.project.name, dependency.name)

    request.cirrina.db_session.commit()  # pylint: disable=no-member
    logger.info("ProjectVersionDependency '%s -> %s' deleted", pv_name, dep_name)

    return web.Response(
        text="Deleted dependency from {} to {}".format(pv_name, dep_name), status=200
    )


@app.http_post("/api/projectversions/{projectversion_id}/dependency")
@app.authenticated
@app.req_role("owner")
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
    params = await request.json()

    projectversion_id = parse_int(request.match_info["projectversion_id"])
    if not projectversion_id:
        return web.Response(text="Incorrect value for projectversion_id", status=400)

    dependency_id = parse_int(params.get("dependency_id"))
    if not dependency_id:
        return web.Response(text="Incorrect value for dependency_id", status=400)

    projectversion = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == projectversion_id)  # pylint: disable=no-member
        .first()
    )
    if not projectversion:
        return web.Response(status=400, text="Invalid data received.")

    if projectversion.is_locked:
        return web.Response(
            text="You can not add dependencies on a locked projectversion!", status=400
        )

    if dependency_id == projectversion_id:
        return web.Response(
            text="You can not add a dependency of the same projectversion to itself!",
            status=400,
        )

    # check for dependency loops
    dep_ids = get_projectversion_deps(dependency_id, request.cirrina.db_session)
    if projectversion_id in dep_ids:
        return web.Response(
            text="You can not add a dependency of a projectversion depending itself on this projectversion!",
            status=400,
        )

    dependency = (
        request.cirrina.db_session.query(ProjectVersion)
        .filter(ProjectVersion.id == dependency_id)  # pylint: disable=no-member
        .first()
    )
    if not dependency:
        return web.Response(status=400, text="Invalid data received.")

    projectversion.dependencies.append(dependency)
    request.cirrina.db_session.commit()

    return web.Response(status=200, text="Dependency added")
