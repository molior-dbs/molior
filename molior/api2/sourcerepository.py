import re
import giturlparse

from sqlalchemy.sql import or_

from ..app import app, logger
from ..auth import req_role, req_admin
from ..tools import ErrorResponse, OKResponse, paginate, array2db, db2array
from ..api.sourcerepository import get_last_gitref, get_last_build
from ..molior.queues import enqueue_task

from ..model.sourcerepository import SourceRepository
from ..model.build import Build
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
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
    produces:
        - text/json
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


@app.http_get("/api2/repository/{repository_id}/dependents")
@app.authenticated
async def get_sourcerepository_dependents(request):
    """
    Returns a list of repository dependents.

    ---
    description: Returns a list of repository dependents.
    tags:
        - SourceRepositories
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
        - name: q
          in: query
          required: false
          type: string
          description: String to filter project name
        - name: unlocked
          in: query
          required: false
          type: boolean
          description: is this repository unlocked?
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
    produces:
        - text/json
    """
    repository_id = request.match_info["repository_id"]
    filter_name = request.GET.getone("q", "")
    unlocked = request.GET.getone("unlocked", "")
    unlocked = unlocked == "true"
    db = request.cirrina.db_session
    repo = db.query(SourceRepository).filter_by(id=repository_id).first()
    if not repo:
        return ErrorResponse(404, "Repository with id {} could not be found!".format(repository_id))
    query = db.query(ProjectVersion).filter(SouRepProVer.projectversion_id == ProjectVersion.id,
                                            SouRepProVer.sourcerepository_id == repo.id)
    if filter_name:
        query = query.filter(ProjectVersion.fullname.ilike("%{}%".format(filter_name)))
    if unlocked:
        query = query.filter(ProjectVersion.is_locked.is_(False))
    query = query.order_by(ProjectVersion.fullname)
    nb_results = query.count()
    query = paginate(request, query)
    dependents = query.all()
    results = []
    for dependent in dependents:
        results.append(dependent.data())
    data = {"total_result_count": nb_results, "results": results}
    return OKResponse(data)


@app.http_get("/api2/repositories")
@app.authenticated
async def get_repositories2(request):
    """
    Returns source repositories with the given filters applied.

    ---
    description: Returns source repositories with the given filters applied.
    tags:
        - SourceRepositories
    parameters:
        - name: filter_url
          in: query
          required: false
          type: string
        - name: q
          in: query
          required: false
          type: string
        - name: exclude_projectversion_id
          in: query
          required: false
          type: integer
    produces:
        - text/json
    """
    db = request.cirrina.db_session
    url = request.GET.getone("filter_url", "")
    filter_name = request.GET.getone("q", "")
    exclude_projectversion_id = request.GET.getone("exclude_projectversion_id", "")
    try:
        exclude_projectversion_id = int(exclude_projectversion_id)
    except Exception:
        exclude_projectversion_id = -1

    query = db.query(SourceRepository)

    if url:
        terms = re.split("[/ ]", url)
        for term in terms:
            if not term:
                continue
            query = query.filter(SourceRepository.url.ilike("%{}%".format(term)))

    if filter_name:
        query = query.filter(SourceRepository.name.ilike("%{}%".format(filter_name)))

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
# @app.authenticated
async def get_projectversion_repositories(request):
    """
    Returns source repositories for given project version with the given filters applied.

    ---
    description: Returns source repositories for given project version with the given filters applied.
    tags:
        - SourceRepositories
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: filter_url
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
        - name: per_page
          in: query
          required: false
          type: integer
    produces:
        - text/json
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
        query = query.filter(SourceRepository.url.ilike("%{}%".format(filter_url)))

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
                    "buildstate": build.buildstate,
                    "sourcename": build.sourcename,
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
        - SourceRepositories
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
                url:
                    type: string
                buildvariants:
                    type: array
                    example: [1, 2]
                architectures:
                    required: true
                    type: array
                    items:
                        type: string
                    description: E.g. i386, amd64, arm64, armhf, ...
                    example: ["amd64", "armhf"]
                startbuild:
                    type: boolean
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid data received.
    """
    params = await request.json()
    url = params.get("url", "")
    architectures = params.get("architectures", [])
    startbuild = params.get("startbuild", "true")
    startbuild = startbuild == "true"

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

    for arch in architectures:
        if arch not in db2array(projectversion.mirror_architectures):
            return ErrorResponse(400, "Invalid architecture: " + arch)

    db = request.cirrina.db_session
    repo = db.query(SourceRepository).filter(SourceRepository.url == url).first()
    if not repo:
        query = db.query(SourceRepository).filter(or_(
                    SourceRepository.url.ilike("%{}%{}%/{}".format(repoinfo.resource, repoinfo.owner, repoinfo.name)),
                    SourceRepository.url.ilike("%{}%{}%/{}.git".format(repoinfo.resource, repoinfo.owner, repoinfo.name))))
        if query.count() > 1:
            repo = query.first()
            logger.info("found %d similar repos {} for {} {} {} - using first".format(query.count(), repo.url, repoinfo.resource,
                                                                                      repoinfo.owner, repoinfo.name))
        elif query.count() == 1:
            repo = query.first()
            logger.info("found similar repo {} for {} {} {}".format(repo.url, repoinfo.resource, repoinfo.owner, repoinfo.name))
        else:
            repo = SourceRepository(url=url, name=repoinfo.name.lower(), state="new")
            db.add(repo)

    if repo not in projectversion.sourcerepositories:
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
            sourcename=repo.name,
            buildstate="new",
            buildtype="build",
            sourcerepository=repo,
            maintainer=None
        )

        db.add(build)
        db.commit()
        await build.build_added()

        args = {"clone": [build.id, repo.id]}
        await enqueue_task(args)

    else:  # existing repo
        if startbuild:
            build = Build(
                version=None,
                git_ref=None,
                ci_branch=None,
                is_ci=None,
                sourcename=repo.name,
                buildstate="new",
                buildtype="build",
                sourcerepository=repo,
                maintainer=None,
            )

            request.cirrina.db_session.add(build)
            request.cirrina.db_session.commit()
            await build.build_added()

            args = {"buildlatest": [repo.id, build.id]}
            await enqueue_task(args)

    return OKResponse("SourceRepository added")


@app.http_get("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
@req_role(["member", "owner"])
async def get_projectversion_repository(request):
    """
    Returns source repository for a given project version.

    ---
    description: Returns source repository for a given project version.
    tags:
        - SourceRepositories
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
    produces:
        - text/json
    """
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
        "architectures": db2array(buildconfig.architectures)
    }
    return OKResponse(data)


@app.http_put("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
@req_role(["member", "owner"])
async def edit_repository(request):
    """
    Edit the source repositories of a given project version.

    ---
    description: Returns a repository.
    tags:
        - SourceRepositories
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                architectures:
                    required: true
                    type: array
                    items:
                        type: string
                    description: E.g. i386, amd64, arm64, armhf, ...
                    example: ["amd64", "armhf"]
    produces:
        - text/json
    """
    params = await request.json()
    sourcerepository_id = request.match_info["sourcerepository_id"]
    architectures = params.get("architectures", [])
    if not architectures:
        return ErrorResponse(400, "No architectures received")

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(404, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    for arch in architectures:
        if arch not in db2array(projectversion.mirror_architectures):
            return ErrorResponse(400, "The architecture is not invalid, it is not supported in this projectversion: " + arch)

    db = request.cirrina.db_session
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
    """
    Returns hooks of the source repository of a given project version.

    ---
    description: Returns hooks of the source repository of a given project version.
    tags:
        - SourceRepositories
    parameters:
        - name: project_id
          in: path
          required: true
          type: integer
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
    produces:
        - text/json
    """
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
        hooktype = ""
        if postbuildhook.hook.notify_overall:
            hooktype = "top"
        if postbuildhook.hook.notify_deb:
            if hooktype:
                hooktype += "+"
            hooktype += "deb"
        if postbuildhook.hook.notify_src:
            if hooktype:
                hooktype += "+"
            hooktype += "src"

        data["results"].append({
            "id": postbuildhook.id,
            "method": postbuildhook.hook.method,
            "url": postbuildhook.hook.url,
            "skipssl": postbuildhook.hook.skip_ssl,
            "hooktype": hooktype,
            "body": postbuildhook.hook.body,
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
        - SourceRepositories
    parameters:
        - name: projectversion_id
          in: path
          required: true
          type: integer
        - name: sourcerepository_id
          in: path
          required: true
          type: integer
        - name: repository_id
          in: path
          required: true
          type: integer
          description: id of the repository to get
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                url:
                    type: string
                skipssl:
                    type: boolean
                body:
                    type: string
                hooktype:
                    type: string
                method:
                    type: string
                    example: post/get/...
    produces:
        - text/json
    """
    sourcerepository_id = request.match_info["sourcerepository_id"]
    params = await request.json()
    url = params.get("url", "")
    skip_ssl = params.get("skipssl", "")
    body = params.get("body", "")
    hooktype = params.get("hooktype", "top")
    method = params.get("method", "").lower()

    if not url:
        return ErrorResponse(400, "No URL received")
    if not body:
        return ErrorResponse(400, "No Body received")
    if method not in ["post", "get"]:
        return ErrorResponse(400, "Invalid method received")

    skip_ssl = skip_ssl == "true"

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    db = request.cirrina.db_session
    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    notify_overall = "top" in hooktype
    notify_deb = "deb" in hooktype
    notify_src = "src" in hooktype
    hook = Hook(url=url, method=method, body=body, skip_ssl=skip_ssl,
                notify_overall=notify_overall, notify_deb=notify_deb, notify_src=notify_src)
    db.add(hook)
    db.commit()
    postbuildhook = PostBuildHook(sourcerepositoryprojectversion_id=buildconfig.id, hook_id=hook.id)
    db.add(postbuildhook)
    db.commit()

    return OKResponse("Hook added")


@app.http_put("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}/hook/{hook_id}")
@req_role(["member", "owner"])
async def edit_repository_hook(request):
    """
    Edits postbuild hook.

    ---
    description: Edits postbuild hook.
    tags:
        - SourceRepositories
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
        - name: hook_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                url:
                    type: string
                skipssl:
                    type: boolean
                body:
                    type: string
                hooktype:
                    type: string
                method:
                    type: string
                    example: post/get/...
    produces:
        - text/json
    """
    sourcerepository_id = request.match_info["sourcerepository_id"]
    hook_id = request.match_info["hook_id"]
    params = await request.json()
    url = params.get("url", "")
    skip_ssl = params.get("skipssl", "")
    body = params.get("body", "")
    hooktype = params.get("hooktype", "top")
    method = params.get("method", "").lower()
    hook_enabled = params.get("enabled", "")

    if not url:
        return ErrorResponse(400, "No URL received")
    if not body:
        return ErrorResponse(400, "No Body received")
    if method not in ["post", "get"]:
        return ErrorResponse(400, "Invalid method received")

    skip_ssl = skip_ssl == "true"
    hook_enabled = hook_enabled == "true"

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    db = request.cirrina.db_session
    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    notify_overall = "top" in hooktype
    notify_deb = "deb" in hooktype
    notify_src = "src" in hooktype
    postbuildhook = db.query(PostBuildHook).filter_by(sourcerepositoryprojectversion_id=buildconfig.id, id=hook_id).first()
    if not postbuildhook:
        return ErrorResponse(404, "Hook not found")
    postbuildhook.hook.method = method
    postbuildhook.hook.body = body
    postbuildhook.hook.url = url
    postbuildhook.hook.skip_ssl = skip_ssl
    postbuildhook.hook.notify_src = notify_src
    postbuildhook.hook.notify_deb = notify_deb
    postbuildhook.hook.notify_overall = notify_overall
    postbuildhook.hook.enabled = hook_enabled
    db.commit()

    return OKResponse("Hook changed")


@app.http_delete("/api2/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}/hook/{hook_id}")
@req_role(["member", "owner"])
async def delete_repository_hook(request):
    """
    Deletes given hook from sourcerepository.

    ---
    description: Deletes given hook from sourcerepository.
    tags:
        - SourceRepositories
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
        - name: hook_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    """
    sourcerepository_id = request.match_info["sourcerepository_id"]
    hook_id = request.match_info["hook_id"]

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Project not found")
    if projectversion.is_locked:
        return ErrorResponse(400, "Projectversion is locked")

    db = request.cirrina.db_session
    buildconfig = db.query(SouRepProVer).filter(SouRepProVer.sourcerepository_id == sourcerepository_id,
                                                SouRepProVer.projectversion_id == projectversion.id).first()
    if not buildconfig:
        return ErrorResponse(404, "SourceRepository not found in project")

    hook = db.query(PostBuildHook).filter_by(sourcerepositoryprojectversion_id=buildconfig.id, id=hook_id).first()
    if not hook:
        return ErrorResponse(404, "Hook not found")

    db.delete(hook)
    db.commit()

    return OKResponse("Hook deleted")


@app.http_put("/api2/repository/{repository_id}/merge")
@req_admin
async def merge_repository(request):
    """
    Merges repository.

    ---
    description: Merges repository.
    tags:
        - SourceRepositories
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                duplicate:
                    type: integer
                    description: duplicate repository id
    """
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
    await enqueue_task(args)

    return OKResponse("SourceRepository changed")


@app.http_delete("/api2/repository/{repository_id}")
@req_admin
async def delete_repository(request):
    """
    Deletes repository.

    ---
    description: Deletes repository.
    tags:
        - SourceRepositories
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
    """
    repository_id = request.match_info["repository_id"]
    try:
        repository_id = int(repository_id)
    except Exception:
        return ErrorResponse(400, "Invalid parameter received")

    db = request.cirrina.db_session
    repo = db.query(SourceRepository).filter(SourceRepository.id == repository_id).first()
    if not repo:
        return ErrorResponse(404, "Repository not found")

    builds = db.query(Build).filter(Build.sourcerepository_id == repository_id).all()

    if repo.projectversions:
        return ErrorResponse(400, "Repository cannot be deleted because it is used by project(s)")
    if repo.projectversions or builds:
        return ErrorResponse(400, "Repository cannot be deleted because there are builds using it")

    args = {"delete_repo": [repository_id]}
    await enqueue_task(args)
    return OKResponse("Repository deleted")


@app.http_put("/api2/repository/{repository_id}")
@req_admin
async def edit_repository2(request):
    """
    Edits repository.

    ---
    description: Edits repository.
    tags:
        - SourceRepositories
    parameters:
        - name: repository_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                url:
                    type: string
    """
    repository_id = request.match_info["repository_id"]
    try:
        repository_id = int(repository_id)
    except Exception:
        return ErrorResponse(400, "Invalid parameter received")
    params = await request.json()
    url = params.get("url", "")
    if not url:
        return ErrorResponse(400, "No URL received")

    db = request.cirrina.db_session
    repo = db.query(SourceRepository).filter(SourceRepository.id == repository_id).first()
    if not repo:
        return ErrorResponse(404, "Repository not found")

    if repo.url != url:
        args = {"repo_change_url": [repository_id, url]}
        await enqueue_task(args)
    return OKResponse("Repository changed")
