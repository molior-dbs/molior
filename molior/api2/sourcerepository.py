import uuid
import giturlparse

from sqlalchemy.sql import or_
from aiohttp import web

from molior.app import app, logger
from molior.auth import req_role
from molior.model.sourcerepository import SourceRepository
from molior.model.build import Build
from molior.model.buildtask import BuildTask
from molior.model.buildvariant import BuildVariant
from molior.model.buildconfiguration import BuildConfiguration
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion, get_projectversion
from molior.model.sourepprover import SouRepProVer
from molior.model.architecture import Architecture
from molior.tools import ErrorResponse, paginate

# FIXME: move to tools/model:
from ..api.sourcerepository import get_last_gitref, get_architectures


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
    db = request.cirrina.db_session
    url = request.GET.getone("url", "")
    repositories = db.query(SourceRepository)

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
    project_id = request.match_info["project_id"]
    projectversion_id = request.match_info["projectversion_id"]
    filter_url = request.GET.getone("filter_url", "")

    projectversion = db.query(ProjectVersion).filter(
            ProjectVersion.name == projectversion_id).join(Project).filter(
            Project.name == project_id).first()
    if not projectversion:
        return ErrorResponse(404, "Project with name {} could not be found".format(project_id))

    query = db.query(SourceRepository)
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
                    db, item, projectversion
            ),
            "architectures": get_architectures(
                db, item, projectversion
            ),
        }
        for item in results
    ]
    return web.json_response(data)


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
                SourceRepository.url.like("%{}%{}%{}".format(repoinfo.resource, repoinfo.owner, repoinfo.name)),
                SourceRepository.url.like("%{}%{}%{}.git".format(repoinfo.resource, repoinfo.owner, repoinfo.name))))
    if query.count() == 1:
        repo = query.first()
        logger.info("found existing repo {} for {} {} {}".format(repo.url, repoinfo.resource, repoinfo.owner, repoinfo.name))
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
        await build.build_added()

        token = uuid.uuid4()
        buildtask = BuildTask(build=build, task_id=str(token))
        db.add(buildtask)
        db.commit()

        args = {"clone": [build.id, repo.id]}
        await request.cirrina.task_queue.put(args)

    return web.Response(status=200, text="SourceRepository added")
