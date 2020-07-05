import uuid

from aiohttp import web

from ..app import app, logger
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.sourcerepository import SourceRepository
from ..molior.configuration import Configuration

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@app.http_post("/api/build/gitlab")
async def gitlab_event(request):
    """
    Parse incoming events from a GitLab instance.

    ---
    description: Parse data
    tags:
        - TriggerBuild
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: object_kind
          in: body
          required: true
          type: string
        - name: event_name
          in: body
          required: true
          type: string
        - name: ref
          in: body
          required: false
          type: string
        - name: checkout_sha
          in: body
          required: false
          type: string
        - name: user_id
          in: body
          required: false
          type: integer
        - name: user_username
          in: body
          required: false
          type: string
        - name: user_name
          in: body
          required: false
          type: string
        - name: user_email
          in: body
          required: false
          type: string
         - name: project_id
          in: body
          required: false
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: bad request
        "422":
            description: unprocessable entity
        "500":
            description: internal server error
        "503":
            description: service unavailable
    """

    # Skip any processing in MAINTENANCE mode
    maintenance_mode = False
    query = "SELECT value from metadata where name = :key"
    result = request.cirrina.db_session.execute(query, {"key": "maintenance_mode"})
    for value in result:
        if value[0] == "true":
            maintenance_mode = True
        break

    if maintenance_mode:
        return web.Response(status=503, text="Maintenance Mode")

    # Get auth token 'X-Gitlab-Token' from request header (gitlab)
    gitlab_auth_token = None
    if "X-Gitlab-Token" in request.headers:
        gitlab_auth_token = request.headers["X-Gitlab-Token"]
        logger.debug("GitLab-API: AUTH (X-Gitlab-Token): %s", gitlab_auth_token)
    else:
        logger.warning("GitLab-API: X-Gitlab-Token is missing in request header")
        logger.debug("GitLab-API: headers: %s", request.headers)

    # Get event hook from request header
    event_hook = None
    if "X-Gitlab-Event" in request.headers:
        event_hook = request.headers["X-Gitlab-Event"]
        logger.debug("GitLab-API: EVENT (X-Gitlab-Event): %s", event_hook)
    else:
        logger.warning("GitLab-API: X-Gitlab-Event is missing in request header")
        logger.debug("GitLab-API: headers: %s", request.headers)

    # Require authentication
    if not is_gitlab_auth_token_valid(gitlab_auth_token):
        logger.warning("GitLab-API: Unauthorized access detected")
        logger.debug("GitLab-API: Access not authorized: %s", await request.json())
        return web.Response(status=401, text="Unauthorized")

    # Read object from request body (after successful AUTH only)
    data = await request.json()
    object_kind = data.get("object_kind")
    event_name = data.get("event_name")

    logger.debug("GitLab-API: Incoming event (object_kind): %s", object_kind)
    logger.debug("GitLab-API: Incoming event (event_name): %s", event_name)

    # Validate request and execute method accordingly
    if object_kind == "tag_push" or event_hook == "Tag Push Hook":
        result_message, result_status = await process_tag_push(request, data)

    elif object_kind == "push" or event_hook == "Push Hook":
        result_message, result_status = await process_push(request, data)

    else:
        logger.warning("GitLab-API: Rejecting incoming event (object_kind): %s", object_kind)
        logger.debug("GitLab-API: Received illegible data: %s", data)
        return web.Response(text="Unknown event", status=400)

    if result_status:
        return web.Response(text=result_message, status=result_status)

    return web.Response(text="Unknown error", status=500)


def is_gitlab_auth_token_valid(token):

    # TODO: Implement more sophisticated user-based auth mechanism
    config = Configuration()
    auth_token = config.gitlab.get("auth_token")
    if auth_token and token == auth_token:
        logger.debug("GitLab-API: Access authorized")
        return True

    # Grant access when no token is set in config
    elif not auth_token:
        return True

    # Authentication failed
    else:
        return False


async def process_tag_push(request, data):
    """
    Process incoming TAG_PUSH event from a GitLab instance.

     Args:
        request: The request instance.
        data (dict): The received data.
   """

    event_name = data.get("event_name")
    logger.info("GitLab-API: Incoming event (event_name): %s", event_name)

    user_username = data.get("user_username")
    logger.info("GitLab-API: TAG_PUSH (user_username): %s", user_username)

    user_name = data.get("user_name")
    logger.info("GitLab-API: TAG_PUSH (user_name): %s", user_name)

    git_ref = data.get("ref")
    logger.info("GitLab-API: TAG_PUSH (git_ref): %s", git_ref)

    user_email = data.get("user_email")
    logger.debug("GitLab-API: TAG_PUSH (user_email): %s", user_email)

    repository_url = ""
    project = data.get("project")
    if project:
        project_name = project.get("name")
        logger.info("GitLab-API: TAG_PUSH (project_name): %s", project_name)

        url = project.get("url")
        logger.debug("GitLab-API: TAG_PUSH (url): %s", url)

        ssl_url = project.get("ssl_url")
        logger.debug("GitLab-API: TAG_PUSH (ssl_url): %s", ssl_url)

        git_ssl_url = project.get("git_ssl_url")
        logger.debug("GitLab-API: TAG_PUSH (git_ssl_url): %s", git_ssl_url)

        if git_ssl_url:
            repository_url = git_ssl_url
        elif ssl_url:
            repository_url = ssl_url
        elif url:
            repository_url = url

    if not repository_url:
        repository = data.get("repository")
        if repository:
            url = repository.get("url")
            git_ssl_url = repository.get("git_ssl_url")

            if git_ssl_url:
                repository_url = git_ssl_url
            elif url:
                repository_url = url

    if not repository_url:
        return "Missing GIT repository URL (ssh)", 400
    else:
        logger.info("GitLab-API: TAG_PUSH (repository): %s", repository_url)

    # Prepare branch (used for UI only) from parsed data
    ui_branch = None
    if git_ref:
        tag_left = "refs/tags/"
        if git_ref.startswith(tag_left):
            ui_branch = git_ref[len(tag_left):]

        ref_left = "refs/heads/"
        if git_ref.startswith(ref_left):
            ui_branch = git_ref[len(ref_left):]

    repo = (
        request.cirrina.db_session.query(SourceRepository)
        .filter(SourceRepository.url == repository_url)
        .first()
    )
    if not repo:
        return "Repo not found", 400

    build = Build(
        version=None,
        git_ref=git_ref,
        ci_branch=ui_branch,
        is_ci=False,
        versiontimestamp=None,
        sourcename=repo.name,
        buildstate="new",
        buildtype="build",
        sourcerepository=repo,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    request.cirrina.db_session.commit()
    await build.build_added()

    token = uuid.uuid4()
    build_task = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(build_task)
    request.cirrina.db_session.commit()

    logger.debug("GitLab-API: CI-BUILD  (build_id): %s", build.id)
    if git_ref and repo.id:
        args = {"build": [build.id, repo.id, git_ref, ui_branch]}

        # Queue new build job
        if await request.cirrina.task_queue.put(args):
            logger.info("GitLab-API: BUILD triggered (sourcename): %s", build.sourcename)
            return "OK", 200

    return "Unprocessable Entity", 422


async def process_push(request, data):
    """
    Process incoming PUSH event from a GitLab instance.

    Args:
        request: The request instance.
        data (dict): The received data.
    """

    user_username = data.get("user_username")
    logger.info("GitLab-API: PUSH (user_username): %s", user_username)

    user_name = data.get("user_name")
    logger.info("GitLab-API: PUSH (user_name): %s", user_name)

    user_email = data.get("user_email")
    logger.debug("GitLab-API: PUSH (user_email): %s", user_email)

    git_ref = data.get("ref")
    logger.info("GitLab-API: PUSH (git_ref): %s", git_ref)

    checkout_sha = data.get("checkout_sha")
    logger.info("GitLab-API: PUSH (checkout_sha): %s", checkout_sha)

    repository_url = ""
    project = data.get("project")
    if project:

        project_ssh_url = project.get("ssh_url")
        logger.debug("GitLab-API: PUSH (project_ssh_url): %s", project_ssh_url)

        project_name = project.get("name")
        logger.info("GitLab-API: PUSH (project_name): %s", project_name)

        project_url = project.get("url")
        logger.debug("GitLab-API: PUSH (project_url): %s", project_url)

        project_git_ssh_url = project.get("git_ssh_url")
        logger.debug("GitLab-API: PUSH (project_git_ssh_url): %s", project_git_ssh_url)

        if project_git_ssh_url:
            repository_url = project_git_ssh_url
        elif project_ssh_url:
            repository_url = project_ssh_url
        elif project_url:
            repository_url = project_url

    if not repository_url:
        repository = data.get("repository")
        if repository:
            repository_urlx = repository.get("url")
            logger.debug("GitLab-API: PUSH (repository_urlx): %s", repository_urlx)

            repository_git_ssh_url = repository.get("git_ssh_url")
            logger.debug("GitLab-API: PUSH (repository_git_ssh_url): %s", repository_git_ssh_url)

            if repository_git_ssh_url:
                repository_url = repository_git_ssh_url

            elif repository_urlx:
                repository_url = repository_urlx

    if not repository_url:
        return "Missing GIT repository URL (ssh)", 400
    else:
        logger.info("GitLab-API: PUSH (repository_url): %s", repository_url)

    # Prepare CI/CD branch from parsed data
    ci_branch = None
    if git_ref:
        tag_left = "refs/tags/"
        if git_ref.startswith(tag_left):
            # Skip processing of TAG_PUSH events
            logger.debug("GitLab-API: PUSH unhandled due to TAG_PUSH object")
            return "No TAG_PUSH objects allowed here", 400

        ref_left = "refs/heads/"
        if git_ref.startswith(ref_left):
            ci_branch = git_ref[len(ref_left):]

    # No further processing for API-tests with empty event_name
    # BEWARE: API-test from GitLab will have event_name set to 'push', so be careful
    event_name = data.get("event_name")
    if not event_name:
        logger.info("GitLab-API: TEST: Tickle, tickle ... Hihihi")
        return "OK", 200

    # CI-Branch
    logger.info("GitLab-API: PUSH (ci_branch): %s", ci_branch)

    repo = (
        request.cirrina.db_session.query(SourceRepository)
        .filter(SourceRepository.url == repository_url)
        .first()
    )
    if not repo:
        return "Repo not found", 400

    build = Build(
        version=None,
        git_ref=checkout_sha,       # Use pure hash for CI-builds, instead of git_ref/branch
        ci_branch=ci_branch,
        is_ci=False,
        versiontimestamp=None,
        sourcename=repo.name,
        buildstate="new",
        buildtype="build",
        sourcerepository=repo,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    request.cirrina.db_session.commit()
    await build.build_added()

    token = uuid.uuid4()
    build_task = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(build_task)
    request.cirrina.db_session.commit()

    logger.debug("GitLab-API: CI-BUILD  (build_id): %s", build.id)
    if checkout_sha and repo.id:
        args = {"build": [build.id, repo.id, checkout_sha, ci_branch]}

        # Queue new build job
        if await request.cirrina.task_queue.put(args):
            logger.info("GitLab-API: CI-BUILD triggered (sourcename): %s", build.sourcename)
            return "OK", 200

    return "Unprocessable Entity", 422
