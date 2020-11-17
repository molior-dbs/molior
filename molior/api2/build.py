from ..app import app, logger
from ..model.build import Build
from ..molior.queues import enqueue_aptly
from ..tools import OKResponse, ErrorResponse


@app.http_delete("/api2/build/{build_id}")
@app.authenticated
async def delete_build(request):
    build_id = request.match_info["build_id"]
    try:
        build_id = int(build_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for build_id")

    build = request.cirrina.db_session.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found" % build_id)
        return ErrorResponse(404, "Build not found")

    topbuild = None
    if build.buildtype == "deb":
        topbuild = build.parent.parent
    elif build.buildtype == "source":
        topbuild = build.parent
    elif build.buildtype == "build":
        topbuild = build

    if not topbuild:
        return ErrorResponse(400, "Build cannot be deleted")

    if topbuild.buildstate == "new" or \
       topbuild.buildstate == "scheduled" or \
       topbuild.buildstate == "building" or \
       topbuild.buildstate == "needs_publish" or \
       topbuild.buildstate == "publishing":
        return ErrorResponse(400, "Build in state %s cannot be deleted" % topbuild.buildstate)

    await enqueue_aptly({"delete_build": [topbuild.id]})
    return OKResponse("Build is being deleted")
