import uuid
import logging

from aiohttp import web

from .app import app
from molior.molior.notifier import build_added
from molior.model.build import Build
from molior.model.buildtask import BuildTask
from molior.model.sourcerepository import SourceRepository

logger = logging.getLogger("molior-web")

# {
#    "push" : {
#       "changes" : [
#          {
#             "old" : {
#                "target" : {
#                   "hash" : "0460453b5c3b6f0cbe705...",
#                   "type" : "commit"
#                },
#                "name" : "feature/one",
#                "type" : "branch"
#             },
#             "created" : false,
#             "closed" : false,
#             "new" : {
#                "target" : {
#                   "type" : "commit",
#                   "hash" : "1460453b5c3b6f0cbe705..."
#                },
#                "name" : "feature/two",
#                "type" : "branch"
#             }
#          }
#       ]
#    },
#    "actor" : {
#       "emailAddress" : "j@ibitbucket.com",
#       "username" : "jjj",
#       "displayName" : "J. J."
#    },
#    "repository" : {
#       "scmId" : "git",
#       "slug" : "gitrepo",
#       "links" : {
#          "self" : [
#             {
#                "href" : "https://bitbucket.com/stash/projects/PROJECT/repos/gitrepo/browse"
#             }
#          ]
#       },
#       "ownerName" : "PROJECT",
#       "fullName" : "PROJECT/gitrepo",
#       "public" : true,
#       "project" : {
#          "key" : "PROJECT",
#          "name" : "gitproject"
#       },
#       "owner" : {
#          "username" : "PROJECT",
#          "emailAddress" : null,
#          "displayName" : "PROJECT"
#       }
#    }
# }


@app.http_post("/api/build/bitbucket")
async def bitbucket_trigger(request):
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

    try:
        data = await request.json()
        logger.info(data)
        url = data["repository"]["links"]["self"][0]["href"]
        git_ref = data["push"]["changes"][0]["new"]["target"]["hash"]
        branch = data["push"]["changes"][0]["new"]["name"]

        # https://bitbucket.com/stash/projects/PROJECT/repos/gitrepo/browse
        parts = url.split("/")
        project = parts[5].lower()
        repo = parts[7].lower()

    except Exception as exc:
        logger.exception(exc)
        return web.Response(status=404, text="Error parsing trigger data")

    repo = request.cirrina.db_session.query(SourceRepository).filter(SourceRepository.url.like("%/{}/{}.git".format(project, repo))).first()
    if not repo:
        logger.warning("bitbucket trigger: reposiroty not found: {}".format(url))
        return web.Response(status=404, text="Repository not found")

    build = Build(
        version=None,
        git_ref=git_ref,
        ci_branch=branch,
        is_ci=False,
        versiontimestamp=None,
        sourcename=repo.name,
        buildstate="new",
        buildtype="build",
        buildconfiguration=None,
        sourcerepository=repo,
        maintainer=None,
    )

    request.cirrina.db_session.add(build)
    request.cirrina.db_session.commit()
    await build_added(build)

    token = uuid.uuid4()
    build_task = BuildTask(build=build, task_id=str(token))
    request.cirrina.db_session.add(build_task)
    request.cirrina.db_session.commit()

    args = {"build": [build.id, repo.id, git_ref, branch]}
    await request.cirrina.task_queue.put(args)

    return web.Response(status=200, text="OK")
