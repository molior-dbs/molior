import json
import uuid

from aiohttp import web

from ..app import app, logger
from ..tools import ErrorResponse, OKResponse, parse_int, get_hook_triggers, paginate, db2array
from ..model.sourcerepository import SourceRepository
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.projectversion import ProjectVersion
from ..model.sourepprover import SouRepProVer
from ..molior.queues import enqueue_task


def get_last_gitref(repo, db):
    last_build = db.query(Build).filter(Build.sourcerepository_id == repo.id,
                                        Build.buildtype == "source").order_by(Build.id.desc()).first()
    if last_build:
        return last_build.git_ref
    return None


def get_last_build(db, projectversion, repository):
    last_build = db.query(Build).filter(Build.sourcerepository_id == repository.id,
                                        Build.projectversion_id == projectversion.id,
                                        Build.buildtype == "deb").order_by(Build.id.desc()).first()
    return last_build


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


def get_architectures(db, repo, projectversion):
    """
    Returns all architectures a repository is configured to build for
    """
    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == repo.id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()

    return db2array(buildconfig.architectures)


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
        - name: page_size
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

    repositories = request.cirrina.db_session.query(SourceRepository)

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
    repositories = paginate(request, repositories)

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
                "dependencies": [
                    {
                        "id": dependency.id,
                        "name": dependency.name,
                        "url": dependency.url,
                        "dependencies": get_dependencies_by_sourcerepository(request.cirrina.db_session, dependency.id),
                    }
                    for dependency in repository.dependencies
                ],
            }
            if projectversion:
                build = get_last_build(request.cirrina.db_session, projectversion, repository)
                repoinfo.update({
                    "projectversion": {
                        "id": projectversion.id,
                        "name": projectversion.project.name,
                        "version": projectversion.name,
                        "last_gitref": get_last_gitref(request.cirrina.db_session, repository),
                        "architectures": get_architectures(request.cirrina.db_session, repository, projectversion),
                        "last_build": {
                            "id": build.id,
                            "version": build.version,
                            "buildstate": build.buildstate
                        }
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

        # FIXME: ????
        data["results"] = [
            {
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
        "data": {"id": db_repo.id, "name": db_repo.name.lower(), "url": db_repo.url},
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
        request.cirrina.db_session.query(SourceRepository)
        .join(SouRepProVer)
        .join(ProjectVersion)
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
        sourcename=repository.name,
        buildstate="new",
        buildtype="build",
        sourcerepository=repository,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    await build.build_added()

    token = uuid.uuid4()
    buildtask = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(buildtask)
    request.cirrina.db_session.commit()

    args = {"clone": [build.id, repository.id]}
    await enqueue_task(args)
    return OKResponse("Clone job started")


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

    logger.debug("trigger_build_latest for repo %d" % repository_id)

    build = Build(
        version=None,
        git_ref=None,
        ci_branch=None,
        is_ci=None,
        sourcename=repository.name,
        buildstate="new",
        buildtype="build",
        sourcerepository=repository,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    request.cirrina.db_session.commit()
    await build.build_added()

    token = uuid.uuid4()
    buildtask = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(buildtask)
    request.cirrina.db_session.commit()

    args = {"buildlatest": [repository_id, build.id]}
    await enqueue_task(args)

    return web.json_response({"build_token": str(token)})
