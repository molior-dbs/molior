import uuid
import giturlparse

from sqlalchemy.sql import or_

from ..app import app, logger
from ..auth import req_role, req_admin
from ..tools import ErrorResponse, OKResponse, paginate, array2db, db2array
from ..api.sourcerepository import get_last_gitref, get_last_build
from ..model.sourcerepository import SourceRepository
from ..model.build import Build
from ..model.buildtask import BuildTask
from ..model.projectversion import ProjectVersion, get_projectversion
from ..model.sourepprover import SouRepProVer
from ..model.postbuildhook import PostBuildHook
from ..model.hook import Hook


@app.http_get("/api2/repository/{repository_id}")
@app.authenticated
async def get_repository(request):
    """
    Returns source repositories with the given filters applied.

    ---
    description: Returns a repository.
    tags:
        - SourceRepositories
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: repository_id
          in: query
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
    """
    repository_id = request.match_info["repository_id"]

    repo = request.cirrina.db_session.query(SourceRepository).filter_by(id=repository_id).first()
    if not repo:
        return ErrorResponse(404, "Repository with id {} could not be found!".format(repository_id))

    data = {
        "id": repo.id,
        "name": repo.name,
        "url": repo.url,
        "state": repo.state,
    }

    return OKResponse(data)


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
        - name: filter_name
          in: query
          required: false
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
    """
    db = request.cirrina.db_session
    url = request.GET.getone("url", "")
    name = request.GET.getone("filter_name", "")
    exclude_projectversion_id = request.GET.getone("exclude_projectversion_id", "")
    try:
        exclude_projectversion_id = int(exclude_projectversion_id)
    except Exception:
        exclude_projectversion_id = -1

    query = db.query(SourceRepository)

    if url:
        query = query.filter(SourceRepository.url.like("%{}%".format(url)))

    if name:
        query = query.filter(SourceRepository.name.like("%{}%".format(name)))

    if exclude_projectversion_id != -1:
        query = query.filter(~SourceRepository.projectversions.any(ProjectVersion.id == exclude_projectversion_id))

    query = query.order_by(SourceRepository.name)
    nb_results = query.count()

    query = paginate(request, query)
    results = query.all()

    data = {"total_result_count": nb_results, "results": []}
    for repo in results:
        data["results"].append({
            "id": repo.id,
            "name": repo.name,
            "url": repo.url,
            "state": repo.state,
        })
    return OKResponse(data)


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
    db = request.cirrina.db_session
    filter_url = request.GET.getone("filter_url", "")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    query = db.query(SourceRepository, SouRepProVer).filter(SouRepProVer.sourcerepository_id == SourceRepository.id,
                                                            SouRepProVer.projectversion_id == projectversion.id)
    query = query.filter(SourceRepository.projectversions.any(id=projectversion.id))

    if filter_url:
        query = query.filter(SourceRepository.url.like("%{}%".format(filter_url)))

    count = query.count()
    query = query.order_by(SourceRepository.name)
    query = paginate(request, query)
    results = query.all()

    data = {"total_result_count": count, "results": []}
    for repo, srpv in results:
        result = {
            "id": repo.id,
            "name": repo.name,
            "url": repo.url,
            "state": repo.state,
            "last_gitref": get_last_gitref(repo, db),
            "architectures": db2array(srpv.architectures),
        }
        build = get_last_build(request.cirrina.db_session, projectversion, repo)
        if build:
            result.update({
                "last_build": {
                    "id": build.id,
                    "version": build.version,
                    "buildstate": build.buildstate
                }
            })
        data["results"].append(result)

    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/repositories")
@req_role(["member", "owner"])
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
        return ErrorResponse(400, "No URL received")
    if not architectures:
        return ErrorResponse(400, "No architectures received")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    try:
        repoinfo = giturlparse.parse(url)
    except giturlparse.parser.ParserError:
        return ErrorResponse(400, "Invalid git URL")

    query = db.query(SourceRepository).filter(or_(
                SourceRepository.url == url,
                SourceRepository.url.like("%{}%{}%{}".format(repoinfo.resource, repoinfo.owner, repoinfo.name)),
                SourceRepository.url.like("%{}%{}%{}.git".format(repoinfo.resource, repoinfo.owner, repoinfo.name))))
    if query.count() == 1:
        repo = query.first()
        logger.info("found existing repo {} for {} {} {}".format(repo.url, repoinfo.resource, repoinfo.owner, repoinfo.name))
        if repo not in projectversion.sourcerepositories:
            projectversion.sourcerepositories.append(repo)
            db.commit()
    else:
        repo = SourceRepository(url=url, name=repoinfo.name, state="new")
        db.add(repo)
        projectversion.sourcerepositories.append(repo)
        db.commit()

    sourepprover = db.query(SouRepProVer).filter(
                          SouRepProVer.sourcerepository_id == repo.id,
                          SouRepProVer.projectversion_id == projectversion.id).first()

    sourepprover.architectures = array2db(architectures)
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
            sourcerepository=repo,
            maintainer=None
        )

        db.add(build)
        db.commit()
        await build.build_added()

        token = uuid.uuid4()
        buildtask = BuildTask(build=build, task_id=str(token))
        db.add(buildtask)
        db.commit()

        args = {"clone": [build.id, repo.id]}
        await request.cirrina.task_queue.put(args)

    return OKResponse("SourceRepository added")


@app.http_get("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
@req_role(["member", "owner"])
async def get_projectversion_repository(request):
    db = request.cirrina.db_session
    sourcerepository_id = request.match_info["sourcerepository_id"]
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(404, "Project not found")

    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    repository = db.query(SourceRepository).filter(SourceRepository.id == sourcerepository_id).first()
    data = {
        "id": repository.id,
        "name": repository.name,
        "url": repository.url,
        "state": repository.state,
    }
    return OKResponse(data)


@app.http_put("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
@req_role(["member", "owner"])
async def edit_repository(request):
    sourcerepository_id = request.match_info["sourcerepository_id"]
    db = request.cirrina.db_session
    params = await request.json()
    architectures = params.get("architectures", [])

    if not architectures:
        return ErrorResponse(400, "No architectures received")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(404, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    buildconfig.architectures = array2db(architectures)
    db.commit()
    return OKResponse("SourceRepository changed")


@app.http_get("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}/hooks")
@req_role(["member", "owner"])
async def get_repository_hooks(request):
    db = request.cirrina.db_session
    sourcerepository_id = request.match_info["sourcerepository_id"]
    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(404, "Project not found")

    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    postbuildhooks = db.query(PostBuildHook).join(Hook).filter(PostBuildHook.sourcerepositoryprojectversion_id == buildconfig.id)
    data = {"total_result_count": postbuildhooks.count(), "results": []}
    for postbuildhook in postbuildhooks:
        data["results"].append({
            "id": postbuildhook.id,
            "method": postbuildhook.hook.method,
            "url": postbuildhook.hook.url,
            "enabled": postbuildhook.hook.enabled,
        })
    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}/hook")
@req_role(["member", "owner"])
async def add_repository_hook(request):
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
    sourcerepository_id = request.match_info["sourcerepository_id"]
    params = await request.json()
    url = params.get("url", "")
    body = params.get("body", "")
    method = params.get("method", "")

    if not url:
        return ErrorResponse(400, "No URL received")
    if not body:
        return ErrorResponse(400, "No Body received")
    if method not in ["post", "get"]:
        return ErrorResponse(400, "Invalid method received")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    hook = Hook(url=url, method=method, body=body)
    db.add(hook)
    db.commit()
    postbuildhook = PostBuildHook(sourcerepositoryprojectversion_id=buildconfig.id, hook_id=hook.id)
    db.add(postbuildhook)
    db.commit()

    return OKResponse("Hook added")


@app.http_put("/api2/repository/{repository_id}/merge")
@req_admin
async def merge_repository(request):
    repository_id = request.match_info["repository_id"]
    try:
        repository_id = int(repository_id)
    except Exception:
        return ErrorResponse(400, "Invalid parameter received")

    params = await request.json()
    duplicate_id = params.get("duplicate")
    try:
        duplicate_id = int(duplicate_id)
    except Exception:
        return ErrorResponse(400, "Invalid parameter received")

    # FIXME get repo id from db
    # get duplicate from db
    # verify stuff (if there is repo behnd those numbers)

    args = {"merge_duplicate_repo": [repository_id, duplicate_id]}
    await request.cirrina.task_queue.put(args)

    return OKResponse("SourceRepository changed")
