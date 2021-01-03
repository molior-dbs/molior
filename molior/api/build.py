import re

from datetime import datetime
from aiohttp import web
from sqlalchemy.sql import func, or_
from sqlalchemy.orm import aliased

from ..app import app, logger
from ..model.build import Build, BUILD_STATES, DATETIME_FORMAT
from ..model.sourcerepository import SourceRepository
from ..model.project import Project
from ..model.projectversion import ProjectVersion
from ..model.maintainer import Maintainer
from ..tools import paginate, ErrorResponse
from ..molior.queues import enqueue_task


@app.http_get("/api/builds")
async def get_builds(request):
    """
    Gets builds from the database.

    ---
    description: Returns a list of builds.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: from
          in: query
          required: false
          type: datetime
        - name: to
          in: query
          required: false
          type: datetime
        - name: currently_failing
          in: query
          required: false
          type: boolean
        - name: count_only
          in: query
          required: false
          type: boolean
        - name: project_version_id
          in: query
          required: false
          type: integer
        - name: sourcerepository_id
          in: query
          required: false
          type: integer
        - name: project_id
          in: query
          required: false
          type: integer
        - name: architecture
          in: query
          required: false
          type: string
        - name: distrelease
          in: query
          required: false
          type: string
        - name: buildvariant
          in: query
          required: false
          type: string
        - name: buildvariant_id
          in: query
          required: false
          type: integer
        - name: sourcerepository
          in: query
          required: false
          type: string
        - name: buildstate
          in: query
          required: false
          type: array
        - name: startstamp
          in: query
          required: false
          type: string
        - name: version
          in: query
          required: false
          type: string
        - name: maintainer
          in: query
          required: false
          type: string
        - name: project
          in: query
          required: false
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    search = request.GET.getone("search", None)
    search_project = request.GET.getone("search_project", None)
    project = request.GET.getone("project", None)
    maintainer = request.GET.getone("maintainer", None)
    commit = request.GET.getone("commit", None)

    # FIXME:
    # buildvariant = request.GET.getone("buildvariant", None)
    # buildvariant_id = request.GET.getone("buildvariant_id", None)
    architecture = request.GET.getone("architecture", None)
    distrelease = request.GET.getone("distrelease", None)
    version = request.GET.getone("version", None)
    sourcerepository_name = request.GET.getone("sourcerepository", None)
    startstamp = request.GET.getone("startstamp", None)
    buildstates = request.GET.getall("buildstate", [])

    try:
        project_version_id = int(request.GET.getone("project_version_id"))
    except (ValueError, KeyError):
        project_version_id = None

#    try:
#        buildvariant_id = int(request.GET.getone("buildvariant_id"))
#    except (ValueError, KeyError):
#        buildvariant_id = None

    try:
        project_id = int(request.GET.getone("project_id"))
    except (ValueError, KeyError):
        project_id = None

    try:
        from_date = datetime.strptime(request.GET.getone("from"), "%Y-%m-%d %H:%M:%S")
    except (ValueError, KeyError):
        from_date = None

    try:
        to_date = datetime.strptime(request.GET.getone("to"), "%Y-%m-%d %H:%M:%S")
    except (ValueError, KeyError):
        to_date = None

    try:
        count_only = request.GET.getone("count_only").lower() == "true"
    except (ValueError, KeyError):
        count_only = False

    try:
        sourcerepository_id = int(request.GET.getone("sourcerepository_id"))
    except (ValueError, KeyError):
        sourcerepository_id = None

    builds = request.cirrina.db_session.query(Build).outerjoin(Build.maintainer)

    if sourcerepository_id:
        builds = builds.filter(Build.sourcerepository_id == sourcerepository_id)
    if project_id:
        builds = builds.filter(Build.projectversion.project.id == project_id)
    if project_version_id:
        builds = builds.filter(Build.projectversion.id == project_version_id)
    if from_date:
        builds = builds.filter(Build.startstamp > from_date)
    if to_date:
        builds = builds.filter(Build.startstamp < to_date)
    if distrelease:
        builds = builds.filter(Project.name.like("%{}%".format(distrelease)))

#    if buildvariant:
#        buildvariant_ids = [
#            b.id
#            for b in (
#                request.cirrina.db_session.query(BuildVariant.id)
#                .join(ProjectVersion)
#                .join(Project)
#                .join(Architecture)
#                .filter(
#                    BuildVariant.name.like("%{}%".format(buildvariant))
#                )
#                .distinct()
#            )
#        ]
#        builds = builds.filter(BuildVariant.id.in_(buildvariant_ids))
#
#    if buildvariant_id:
#        builds = builds.filter(BuildVariant.id == buildvariant_id)

    builds = builds.filter(Build.is_deleted.is_(False))

    if search:
        terms = re.split("[/ ]", search)
        for term in terms:
            if not term:
                continue
            builds = builds.filter(or_(
                Build.sourcename.like("%{}%".format(term)),
                Build.version.like("%{}%".format(term)),
                Build.architecture.like("%{}%".format(term)),
                ))

    if search_project:
        builds = builds.join(ProjectVersion).join(Project)
        terms = re.split("[/ ]", search_project)
        for term in terms:
            if not term:
                continue
            builds = builds.filter(Project.is_mirror.is_(False), or_(
                ProjectVersion.name.like("%{}%".format(term)),
                Project.name.like("%{}%".format(term)),
                ))

    if project:
        if "/" not in project:
            return ErrorResponse(400, "Project not found")
        projectname, projectversion = project.split("/", 1)
        builds = builds.join(ProjectVersion).join(Project).filter(Project.is_mirror.is_(False), or_(
                                ProjectVersion.name == projectversion),
                                Project.name == projectname)

    # FIXME:
    if version:
        builds = builds.filter(Build.version.like("%{}%".format(version)))
    if maintainer:
        builds = builds.filter(Maintainer.fullname.ilike("%{}%".format(maintainer)))
    if commit:
        builds = builds.filter(Build.git_ref.like("%{}%".format(commit)))
    if architecture:
        builds = builds.filter(Build.architecture.like("%{}%".format(architecture)))
    if sourcerepository_name:
        builds = builds.filter(or_(Build.sourcename.like("%{}%.format(sourcerepository_name)"),
                                   Build.sourcerepository.url.like("%/%{}%.git".format(sourcerepository_name))))
    if startstamp:
        builds = builds.filter(func.to_char(Build.startstamp, "YYYY-MM-DD HH24:MI:SS").contains(startstamp))
    if buildstates and set(buildstates).issubset(set(BUILD_STATES)):
        builds = builds.filter(or_(*[Build.buildstate == buildstate for buildstate in buildstates]))

    if search or search_project or project:
        # make sure parents and grandparents are invited
        child_cte = builds.cte(name='childs')
        parentbuilds = request.cirrina.db_session.query(Build).filter(Build.id == child_cte.c.parent_id)
        parent_cte = parentbuilds.cte(name='parents')
        grandparentbuilds = request.cirrina.db_session.query(Build).filter(Build.id == parent_cte.c.parent_id)
        builds = builds.union(parentbuilds, grandparentbuilds)

    nb_builds = builds.count()

    # sort hierarchically

    # select id, parent_id, sourcename, buildtype, (select b2.parent_id from build b2
    # where b2.id = b. parent_id) as grandparent_id, coalesce(parent_id, id, 7) from
    # build b order by coalesce((select b2.parent_id from build b2 where b2.id = b.
    # parent_id), b.parent_id, b.id)desc , b.id;

    parent = aliased(Build)
    builds = builds.outerjoin(parent, parent.id == Build.parent_id)
    builds = builds.order_by(func.coalesce(parent.parent_id, Build.parent_id, Build.id).desc(), Build.id)

    builds = paginate(request, builds)

    data = {"total_result_count": nb_builds, "results": []}
    if not count_only:
        for build in builds:
            data["results"].append(build.data())

    return web.json_response(data)


@app.http_get("/api/builds/{build_id:\\d+}")
@app.authenticated
async def get_build(request):
    """
    Returns a build.

    ---
    description: Returns a build.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: build_id
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
    build_id = request.match_info["build_id"]
    try:
        build_id = int(build_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for build_id", status=400)

    build = request.cirrina.db_session.query(Build).filter(Build.id == build_id).first()
    if not build:
        return web.Response(text="Build not found", status=400)

    maintainer = str()
    if build.maintainer:
        maintainer = "{} {}".format(
            build.maintainer.firstname, build.maintainer.surname
        )

    project = {}
    if build.projectversion:
        project = {"id": build.projectversion.project.id,
                   "name": build.projectversion.project.name,
                   "version": {"id": build.projectversion.id,
                               "name": build.projectversion.name,
                               "is_locked": build.projectversion.is_locked}}

    data = {
        "id": build.id,
        "buildstate": build.buildstate,
        "buildtype": build.buildtype,
        "startstamp": build.startstamp.strftime(DATETIME_FORMAT) if build.startstamp else "",
        "endstamp": build.endstamp.strftime(DATETIME_FORMAT) if build.endstamp else "",
        "version": build.version,
        "maintainer": maintainer,
        "sourcename": build.sourcename,
        # "can_rebuild": build.can_rebuild(request.cirrina.web_session, request.cirrina.db_session),
        "branch": build.ci_branch,
        "git_ref": build.git_ref,
        "architecture": build.architecture,
        "project": project
    }

    if build.sourcerepository:
        data.update(
            {
                "sourcerepository": {
                    "name": build.sourcerepository.name,
                    "url": build.sourcerepository.url,
                    "id": build.sourcerepository.id,
                }
            }
        )

    if build.projectversion:
        basemirror_name = ""
        basemirror_version = ""
        buildvariant = ""
        arch = ""
        if build.projectversion.basemirror:
            basemirror_name = build.projectversion.basemirror.project.name
            basemirror_version = build.projectversion.basemirror.name
            if build.architecture:
                arch = build.architecture
            buildvariant = basemirror_name + "-" + basemirror_version + "/" + arch
        data.update(
            {
                "buildvariant": {
                    "architecture": {
                        "name": build.architecture,
                    },
                    "base_mirror": {
                        "name": basemirror_name,
                        "version": basemirror_version
                    },
                    "name": buildvariant
                }
            }
        )

    return web.json_response(data)


@app.http_put("/api/builds/{build_id}")
@app.authenticated
# FIXME: req_role
async def rebuild_build(request):
    """
    Rebuild a failed build

    ---
    description: Delete a build from database.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: build_id
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
    build_id = request.match_info["build_id"]
    try:
        build_id = int(build_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for build_id", status=400)

    logger.info("rebuilding build %d" % build_id)

    build = request.cirrina.db_session.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found" % build_id)
        return web.Response(text="Build not found", status=400)

    if not build.can_rebuild(request.cirrina.web_session, request.cirrina.db_session):
        logger.error("build %d cannot be rebuilt" % build_id)
        return web.Response(text="This build cannot be rebuilt", status=400)

    args = {"rebuild": [build_id]}
    await enqueue_task(args)
    return web.json_response("Rebuild triggered")


@app.http_post("/api/build")
@app.authenticated
async def trigger_build(request):
    """
    Triggers a build.

    ---
    description: Triggers a build
    tags:
        - TriggerBuild
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: repository
          in: body
          required: true
          type: string
        - name: git_ref
          in: body
          required: false
          type: string
        - name: git_branch
          in: body
          required: false
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    data = await request.json()

    repository = data.get("repository")
    git_ref = data.get("git_ref")
    git_branch = data.get("git_branch")
    targets = data.get("targets")
    force_ci = data.get("force_ci")

    maintenance_mode = False
    query = "SELECT value from metadata where name = :key"
    result = request.cirrina.db_session.execute(query, {"key": "maintenance_mode"})
    for value in result:
        if value[0] == "true":
            maintenance_mode = True
        break

    if maintenance_mode:
        return web.Response(status=503, text="Maintenance Mode")

    if not repository:
        return web.Response(text="Bad Request", status=400)

    repo = request.cirrina.db_session.query(SourceRepository).filter(SourceRepository.url == repository).first()
    if not repo:
        return web.Response(text="Repo not found", status=400)

    repo.log_state("build triggered: %s(%s) force_ci=%s, targets=%s" % (git_ref, git_branch, force_ci, str(targets)))

    build = Build(
        version=None,
        git_ref=git_ref,
        ci_branch=git_branch,
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

    if git_ref == "":
        args = {"buildlatest": [repo.id, build.id]}
    else:
        args = {"build": [build.id, repo.id, git_ref, git_branch, targets, force_ci]}
    await enqueue_task(args)

    return web.json_response({"build_id": str(build.id)})


@app.http_get("/api/build/{build_id}")
async def get_build_info(request):
    """
    Gets build task info.

    ---
    description: Returns a list of builds.
    tags:
        - Builds
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: build_id
          in: query
          required: true
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    build_id = request.match_info["build_id"]
    try:
        build_id = int(build_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for build_id", status=400)

    data = {}

    query = """
WITH RECURSIVE descendants AS (
    SELECT build.id, build.parent_id, 0 depth
    FROM build where build.id = :build_id
UNION
    SELECT p.id, p.parent_id, d.depth+1
    FROM build p
    INNER JOIN descendants d
    ON p.parent_id = d.id
)
SELECT *
FROM descendants order by id;
"""
    result = request.cirrina.db_session.execute(query, {"build_id": build_id})
    build_tree_ids = []
    for row in result:
        build_tree_ids.append((row[0], row[1], row[2]))

    toplevel = None
    parents = {}
    for row in build_tree_ids:
        build_id = row[0]
        depth = row[2]

        build = request.cirrina.db_session.query(Build).filter(Build.id == build_id).first()

        buildjson = build.data()
        parents[build.id] = buildjson

        if build.parent_id:
            if build.parent_id in parents:
                parent = parents[build.parent_id]
                if "childs" not in parent:
                    parent["childs"] = []
                parent["childs"].append(buildjson)
            else:
                logger.info("build tree: parent {} not found".format(build.parent_id))

        if depth == 0:
            toplevel = build_id

    if toplevel:
        data = parents[toplevel]

    return web.json_response(data)
