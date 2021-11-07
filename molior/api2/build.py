from ..app import app, logger
from ..model.build import Build
from ..molior.queues import enqueue_aptly
from ..tools import OKResponse, ErrorResponse


@app.http_delete("/api2/build/{build_id}")
@app.authenticated
async def delete_build(request):
    """
    Delete build from the database.

    ---
    description: Delete build from database.
    tags:
        - Builds
    parameters:
        - name: build_id
          description: id of the build to delete
          in: path
          required: true
          type: integer
    produces:
        - text/json
    """
    build_id = request.match_info["build_id"]
    try:
        build_id = int(build_id)
    except (ValueError, TypeError):
        return ErrorResponse(400, "Incorrect value for build_id")

    db = request.cirrina.db_session
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found" % build_id)
        return ErrorResponse(404, "Build not found")

    topbuild = None
    builds = []
    if build.buildtype == "deb":
        topbuild = build.parent.parent
        builds.extend([build.parent, build.parent.parent])
        for b in build.parent.children:
            builds.append(b)
    elif build.buildtype == "source":
        topbuild = build.parent
        builds.extend([build, build.parent])
        for b in build.children:
            builds.append(b)
    elif build.buildtype == "build":
        topbuild = build
        builds.append(build)
        for b in build.children:
            builds.append(b)
            for c in b.children:
                builds.append(c)

    if not topbuild:
        return ErrorResponse(400, "Build of type %s cannot be deleted" % build.buildtype)

    if build.projectversion and build.projectversion.is_locked:
        return ErrorResponse(400, "Build from locked projectversion cannot be deleted")

    if topbuild.buildstate == "scheduled" or \
       topbuild.buildstate == "building" or \
       topbuild.buildstate == "needs_publish" or \
       topbuild.buildstate == "publishing":
        return ErrorResponse(400, "Build in state %s cannot be deleted" % topbuild.buildstate)

    for b in builds:
        b.is_deleted = True
    db.commit()

    await enqueue_aptly({"delete_build": [topbuild.id]})
    return OKResponse("Build is being deleted")
