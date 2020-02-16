"""
Provides api functions to interact with the SourceRepository
database model.
"""
import json
import logging
from aiohttp import web
import uuid
import giturlparse
from sqlalchemy.sql import or_

from molior.model.sourcerepository import SourceRepository
from molior.model.build import Build
from molior.model.buildtask import BuildTask
from molior.model.buildvariant import BuildVariant
from molior.model.buildconfiguration import BuildConfiguration
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion, get_projectversion
from molior.model.sourepprover import SouRepProVer
from molior.model.architecture import Architecture
from molior.molior.notifier import build_added

from .app import app
from .inputparser import parse_int
from .helper.hook import get_hook_triggers
from .tools import ErrorResponse, paginate

logger = logging.getLogger("molior")


def get_last_gitref(db_session, repo, projectversion):
    last_build = db_session.query(Build).filter(Build.sourcerepository_id == repo.id,
                                                Build.buildtype == "source").order_by(Build.id.desc()).first()
    if last_build:
        return last_build.git_ref
    return None


def get_dependencies_by_sourcerepository(db_session, repository_id):
    """
    Returns recursively the dependencies of the given
    repository_id

    Args:
        repository_id: The id of the repository

    Returns:
        list: Recursive list of dependencies
    """
    repository = db_session.query(SourceRepository).filter(
        SourceRepository.id == repository_id
    )
    repository = repository.first()

    return [
        {
            "id": dependency.id,
            "name": dependency.name,
            "url": dependency.url,
            "dependencies": get_dependencies_by_sourcerepository(
                db_session, dependency.id
            ),
        }
        for dependency in repository.dependencies
    ]


def get_architectures(db_session, repo, projectversion):
    """
    Returns all architectures a repository is configured to build for
    """
    buildconfigs = (
        db_session.query(BuildConfiguration)
        .join(SouRepProVer)
        .filter(SouRepProVer.c.sourcerepository_id == repo.id)
        .filter(SouRepProVer.c.projectversion_id == projectversion.id)
    ).all()
    # remove multiple occurences of the same architecture
    return list(set([b.buildvariant.architecture.name for b in buildconfigs]))


@app.http_get("/api/repositories", threaded=True)
@app.authenticated
async def get_repositories(request):
    """
    Returns source repositories with the given filters applied.

    ---
    description: Returns a repository.
    tags:
        - SourceRepositories
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: false
          type: string
        - name: url
          in: query
          required: false
          type: string
        - name: distinct
          in: query
          required: false
          type: array
        - name: project_version_id
          in: query
          required: false
          type: integer
        - name: page
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
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
    custom_filter = request

    try:
        query = json.loads(custom_filter.GET.getone("q"))
    except (ValueError, KeyError):
        query = None

    try:
        distinct = json.loads(custom_filter.GET.getone("distinct"))
    except (ValueError, KeyError):
        distinct = []

    try:
        project_version_id = int(custom_filter.GET.getone("project_version_id"))
    except (ValueError, KeyError):
        project_version_id = None

    try:
        count_only = custom_filter.GET.getone("count_only").lower() == "true"
    except (ValueError, KeyError):
        count_only = False

    try:
        page = int(custom_filter.GET.getone("page"))
    except (ValueError, KeyError):
        page = None
    if page:
        page = 0 if page < 1 else page

    try:
        per_page = int(custom_filter.GET.getone("per_page"))
    except (ValueError, KeyError):
        per_page = None
    if per_page:
        per_page = 1 if per_page < 1 else per_page

    repositories = request.cirrina.db_session.query(
        SourceRepository
    )  # pylint: disable=no-member

    # Apply project version
    if project_version_id is not None:
        repositories = repositories.filter(
            SourceRepository.projectversions.any(id=project_version_id)
        )

    # Apply query filter
    if query:
        name = query.get("name")
        # TODO: Better SourceRepository filtering
        if name:
            repositories = repositories.filter(
                SourceRepository.url.like("%/%{}%.git".format(name))
            )

        url = query.get("url")
        if url:
            repositories = repositories.filter(
                SourceRepository.url.like("%{}%".format(url))
            )

    if "url" in distinct:
        repositories = repositories.distinct(SourceRepository.url)

    # Count entries
    nb_repositories = repositories.count()  # pylint: disable=no-member
    repositories = repositories.order_by(SourceRepository.name)

    # Apply pagination
    if page and per_page:
        repositories = repositories.offset(page * per_page)
    if per_page:
        repositories = repositories.limit(per_page)

    data = {"total_result_count": nb_repositories}

    projectversion = None
    if project_version_id is not None:
        projectversion = request.cirrina.db_session.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()

    if not count_only:
        data["results"] = []
        for repository in repositories:
            repoinfo = {
                "id": repository.id,
                "name": repository.name,
                "url": repository.url,
                "state": repository.state,
                "hooks": [
                    {
                        "id": hook.id,
                        "url": hook.url,
                        "body": hook.body,
                        "method": hook.method,
                        "enabled": hook.enabled,
                        "triggers": get_hook_triggers(hook),
                    }
                    for hook in repository.hooks
                ],
                "dependencies": [
                    {
                        "id": dependency.id,
                        "name": dependency.name,
                        "url": dependency.url,
                        "dependencies": get_dependencies_by_sourcerepository(
                            request.cirrina.db_session, dependency.id
                        ),
                    }
                    for dependency in repository.dependencies
                ],
            }
            if projectversion:
                repoinfo.update({
                    "projectversion": {
                        "id": projectversion.id,
                        "name": projectversion.project.name,
                        "version": projectversion.name,
                        "last_gitref": get_last_gitref(
                            request.cirrina.db_session, repository, projectversion
                            ),
                        "architectures": get_architectures(
                            request.cirrina.db_session, repository, projectversion
                            ),
                        }
                    })
            else:
                repoinfo.update({"projectversions": [{
                            "id": projectversion.id,
                            "name": projectversion.project.name,
                            "version": projectversion.name,
                            # "last_gitref": get_last_gitref(
                            #     request.cirrina.db_session, repository, projectversion
                            # ),
                        }
                        for projectversion in repository.projectversions
                    ]})
            data["results"].append(repoinfo)
        return web.json_response(data)

        data["results"] = [
            {
                "id": repository.id,
                "name": repository.name,
                "url": repository.url,
                "state": repository.state,
                "hooks": [
                    {
                        "id": hook.id,
                        "url": hook.url,
                        "body": hook.body,
                        "method": hook.method,
                        "enabled": hook.enabled,
                        "triggers": get_hook_triggers(hook),
                    }
                    for hook in repository.hooks
                ],
                "dependencies": [
                    {
                        "id": dependency.id,
                        "name": dependency.name,
                        "url": dependency.url,
                        "dependencies": get_dependencies_by_sourcerepository(
                            request.cirrina.db_session, dependency.id
                        ),
                    }
                    for dependency in repository.dependencies
                ],
                "projectversions": [
                    {
                        "id": projectversion.id,
                        "name": projectversion.project.name,
                        "version": projectversion.name,
                        # "last_gitref": get_last_gitref(
                        #     request.cirrina.db_session, repository, projectversion
                        # ),
                    }
                    for projectversion in repository.projectversions
                ],
            }
            for repository in repositories
        ]

    return web.json_response(data)


@app.http_get("/api2/repositories")
@app.authenticated
async def get_repositories2(request):
    """
    Returns source repositories with the given filters applied.

    ---
    description: Returns a repository.
    tags:
        - SourceRepositories
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: url
          in: query
          required: false
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
    """
    url = request.GET.getone("url", "")
    repositories = request.cirrina.db_session.query(SourceRepository)

    if url:
        repositories = repositories.filter(SourceRepository.url.like("%{}%".format(url)))

    count = repositories.count()
    repositories = repositories.order_by(SourceRepository.name)

    data = {"total_result_count": count, "results": []}
    for repository in repositories:
        data["results"].append({
            "id": repository.id,
            "name": repository.name,
            "url": repository.url,
            "state": repository.state,
        })
    return web.json_response(data)


@app.http_get("/api2/project/{project_id}/{projectversion_id}/repositories")
@app.authenticated
async def get_projectversion_repositories(request):
    """
    Returns source repositories with the given filters applied.

    ---
    description: Returns a repository.
    tags:
        - SourceRepositories
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: false
          type: string
        - name: url
          in: query
          required: false
          type: string
        - name: distinct
          in: query
          required: false
          type: array
        - name: project_version_id
          in: query
          required: false
          type: integer
        - name: page
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
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
    project_id = request.match_info["project_id"]
    projectversion_id = request.match_info["projectversion_id"]
    filter_url = request.GET.getone("filter_url", "")

    projectversion = request.cirrina.db_session.query(ProjectVersion).filter(
            ProjectVersion.name == projectversion_id).join(Project).filter(
            Project.name == project_id).first()
    if not projectversion:
        return ErrorResponse(404, "Project with name {} could not be found".format(project_id))

    query = request.cirrina.db_session.query(SourceRepository)
    query = query.filter(SourceRepository.projectversions.any(id=projectversion.id))
    if filter_url:
        query = query.filter(SourceRepository.url.like("%{}%".format(filter_url)))

    count = query.count()
    query = query.order_by(SourceRepository.name)
    query = paginate(request, query)
    results = query.all()

    data = {"total_result_count": count, "results": []}
    data["results"] = [
        {
            "id": item.id,
            "name": item.name,
            "url": item.url,
            "state": item.state,
            "last_gitref": get_last_gitref(
                    request.cirrina.db_session, item, projectversion
            ),
            "architectures": get_architectures(
                request.cirrina.db_session, item, projectversion
            ),
        }
        for item in results
    ]
    return web.json_response(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/repositories")
@app.req_role(["member", "owner"])
async def add_repository(request):
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
    db = request.cirrina.db_session
    params = await request.json()
    url = params.get("url", "")
    architectures = params.get("architectures", [])

    if not url:
        return ErrorResponse(400, "No URL recieved")
    if not architectures:
        return ErrorResponse(400, "No architectures recieved")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Project not found")

    try:
        repoinfo = giturlparse.parse(url)
    except giturlparse.parser.ParserError:
        return ErrorResponse(400, "Invalid git URL")

    query = db.query(SourceRepository).filter(or_(
                SourceRepository.url == url,
                SourceRepository.url.like("%{}%{}%{}%".format(repoinfo.resource, repoinfo.owner, repoinfo.name))
            ))
    if query.count() == 1:
        repo = query.first()
        if repo not in projectversion.sourcerepositories:
            projectversion.sourcerepositories.append(repo)
            db.commit()
    else:
        repo = SourceRepository(url=url)
        repo.state = "new"
        db.add(repo)
        projectversion.sourcerepositories.append(repo)
        db.commit()

    sourepprover_id = db.query(SouRepProVer).filter(
                          SouRepProVer.c.sourcerepository_id == repo.id,
                          SouRepProVer.c.projectversion_id == projectversion.id).first().id

    for architecture in architectures:
        arch = db.query(Architecture).filter(Architecture.name == architecture).first()
        if not arch:
            # FIXME: delete new repo
            return ErrorResponse(400, "Unknown architecture '{}'".format(arch))

        base_mirror_id = projectversion.buildvariants[0].base_mirror_id
        buildvar = db.query(BuildVariant).filter(
                       BuildVariant.architecture_id == arch.id,
                       BuildVariant.base_mirror_id == base_mirror_id).first()

        buildconf = BuildConfiguration(buildvariant=buildvar, sourcerepositoryprojectversion_id=sourepprover_id)
        db.add(buildconf)

    db.commit()

    if repo.state == "new":
        build = Build(
            version=None,
            git_ref=None,
            ci_branch=None,
            is_ci=None,
            versiontimestamp=None,
            sourcename=repo.name,
            buildstate="new",
            buildtype="build",
            buildconfiguration=None,
            sourcerepository=repo,
            maintainer=None
        )

        db.add(build)
        db.commit()
        await build_added(build)

        token = uuid.uuid4()
        buildtask = BuildTask(build=build, task_id=str(token))
        db.add(buildtask)
        db.commit()

        args = {"clone": [build.id, repo.id]}
        await request.cirrina.task_queue.put(args)

    return web.Response(status=200, text="SourceRepository added")


@app.http_post("/api/repositories")
@app.authenticated
# FIXME: req_role
async def post_repositories(request):
    """
    Creates a new sourcerepository.

    ---
    description: Creates a new sourcerepository.
    tags:
        - SourceRepositories
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: url
          in: query
          required: true
          type: string
        - name: dependency_id
          in: query
          required: false
          type: array
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

    url = params.get("url")
    dependencies = params.get("dependency_id", [])

    if request.cirrina.db_session.query(SourceRepository).filter(SourceRepository.url == url).first():
        return ErrorResponse(400, "SourceRepoistory already exists.")

    db_deps = []
    for dep in dependencies:
        dep_id = parse_int(dep)
        if not dep_id:
            return ErrorResponse(400, "Invalid data received.")

        db_dep = (
            request.cirrina.db_session.query(
                SourceRepository
            )  # pylint: disable=no-member
            .filter(SourceRepository.id == dep_id)
            .first()
        )
        db_deps.append(db_dep)

    db_repo = SourceRepository(url=url)
    db_repo.state = "new"
    db_repo.dependencies = db_deps
    request.cirrina.db_session.add(db_repo)
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    logger.info("SourceRepository '%s' with id '%s' added", db_repo.url, db_repo.id)

    data = {
        "status": 1,
        "message": "SourceRepository successfully created",
        "data": {"id": db_repo.id, "name": db_repo.name, "url": db_repo.url},
    }

    return web.json_response(data)


@app.http_get("/api/repositories/{repository_id}")
@app.authenticated
async def get_repository(request):
    """
    Returns a repository.

    ---
    description: Returns a repository.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: repository_id
          in: path
          required: false
          type: integer
        - name: project_version_id
          in: query
          required: false
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            Incorrect value for repository_id
        "500":
            description: internal server error
    """
    repository_id = request.match_info["repository_id"]

    try:
        project_version_id = int(request.GET.getone("project_version_id"))
    except (ValueError, KeyError):
        project_version_id = None

    try:
        repository_id = int(repository_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for repository_id")

    repository = (
        request.cirrina.db_session.query(SourceRepository)  # pylint: disable=no-member
        .join(SouRepProVer)
        .join(ProjectVersion)
        .join(BuildConfiguration)
        .join(BuildVariant)
    )

    if repository_id:
        repository = repository.filter(SourceRepository.id == repository_id)

    if project_version_id:
        repository = repository.filter(ProjectVersion.id == project_version_id)

    repository = repository.first()

    if project_version_id:
        versions = [
            request.cirrina.db_session.query(ProjectVersion)
            .filter(ProjectVersion.id == project_version_id)
            .first()
        ]
    else:
        versions = repository.projectversions

    if not repository:
        return ErrorResponse(400, "Repository not found")

    data = {
        "id": repository.id,
        "name": repository.name,
        "url": repository.url,
        "state": repository.state,
        "dependencies": [
            {
                "id": dependency.id,
                "name": dependency.name,
                "url": dependency.url,
                "dependencies": get_dependencies_by_sourcerepository(
                    request.cirrina.db_session, dependency.id
                ),
            }
            for dependency in repository.dependencies
        ],
        "projectversions": [
            {
                "architectures": get_architectures(
                    request.cirrina.db_session, repository, version
                ),
                "name": version.fullname,
                "id": version.id,
            }
            for version in versions
        ],
        "hooks": [
            {
                "id": hook.id,
                "method": hook.method,
                "body": hook.body,
                "url": hook.url,
                "skip_ssl": hook.skip_ssl,
                "enabled": hook.enabled,
                "triggers": get_hook_triggers(hook),
            }
            for hook in repository.hooks
        ],
    }

    return web.json_response(data)


# FIXME: this should be in projectversion, in order to handle auth
@app.http_post("/api/repositories/{repository_id}/clone")
@app.authenticated
# FIXME: req_role
async def trigger_clone(request):
    """
    Triggers a clone job on a sourcerepository.

    ---
    description: Triggers a clone job on a sourcerepository.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Incorrect value for repository_id
        "500":
            description: internal server error
    """
    repository_id = request.match_info.get("repository_id")

    try:
        repository_id = int(repository_id)
    except (ValueError, TypeError):
        logger.error("trigger_clone error: invalid repository_id received")
        return ErrorResponse(400, "Incorrect value for repository_id")

    logger.info("trigger_clone build for repo %d" % repository_id)

    repository = (
        request.cirrina.db_session.query(SourceRepository)  # pylint: disable=no-member
        .filter(SourceRepository.id == repository_id)
        .first()
    )
    if not repository:
        logger.error("trigger_clone error: repo %d not found" % repository_id)
        return ErrorResponse(400, "Repository not found")

    if repository.state != "error":
        logger.error("trigger_clone error: repo %d not in error state" % repository_id)
        return ErrorResponse(400, "Repository not in error state")

    build = Build(
        version=None,
        git_ref=None,
        ci_branch=None,
        is_ci=None,
        versiontimestamp=None,
        sourcename=repository.name,
        buildstate="new",
        buildtype="build",
        buildconfiguration=None,
        sourcerepository=repository,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    await build_added(build)

    await build.set_building()

    token = uuid.uuid4()
    buildtask = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(buildtask)
    request.cirrina.db_session.commit()

    args = {"clone": [build.id, repository.id]}
    await request.cirrina.task_queue.put(args)
    return web.Response(status=200, text="Clone job started")


@app.http_post("/api/repositories/{repository_id}/build")
@app.authenticated
# FIXME: req_role
async def trigger_build(request):
    """
    Triggers a build latest job on a sourcerepository.

    ---
    description: Triggers a build latest job on a sourcerepository.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Incorrect value for repository_id
        "500":
            description: internal server error
    """
    repository_id = request.match_info.get("repository_id")

    try:
        repository_id = int(repository_id)
    except (ValueError, TypeError):
        logger.error("trigger_build_latest error: invalid repository_id received")
        return ErrorResponse(400, "Incorrect value for repository_id")

    repository = (
        request.cirrina.db_session.query(SourceRepository)
        .filter(SourceRepository.id == repository_id)
        .first()
    )
    if not repository:
        logger.error("trigger_build_latest error: repo %d not found" % repository_id)
        return ErrorResponse(400, "Repository not found")

    logger.info("trigger_build_latest for repo %d" % repository_id)

    build = Build(
        version=None,
        git_ref=None,
        ci_branch=None,
        is_ci=None,
        versiontimestamp=None,
        sourcename=repository.name,
        buildstate="new",
        buildtype="build",
        buildconfiguration=None,
        sourcerepository=repository,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    request.cirrina.db_session.commit()
    await build_added(build)

    await build.set_building()

    token = uuid.uuid4()
    buildtask = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(buildtask)
    request.cirrina.db_session.commit()

    args = {"buildlatest": [repository_id, build.id]}
    await request.cirrina.task_queue.put(args)

    return web.json_response({"build_token": str(token)})
