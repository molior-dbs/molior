import re
from aiohttp import web

from molior.app import app, logger
from molior.auth import req_admin
# from molior.model.build import Build
from molior.model.project import Project
from molior.model.projectversion import ProjectVersion
# from molior.model.buildvariant import BuildVariant
# from molior.molior.utils import get_aptly_connection
from molior.tools import ErrorResponse


@app.http_post("/api2/mirror")
@req_admin
# FIXME: req_role
async def create_mirror2(request):
    """
    Create a debian mirror.

    ---
    description: Create a debian mirror.
    tags:
        - Mirrors
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: name
          in: query
          required: true
          type: string
          description: name of the mirror
        - name: url
          in: query
          required: true
          type: string
          description: http://host of source
        - name: distribution
          in: query
          required: true
          type: string
          description: trusty, wheezy, jessie, etc.
        - name: components
          in: query
          required: false
          type: array
          description: components to be mirrored
          default: main
        - name: keys
          in: query
          required: false
          type: array
          uniqueItems: true
          collectionFormat: multi
          allowEmptyValue: true
          minItems: 0
          items:
              type: string
          description: repository keys
        - name: keyserver
          in: query
          required: false
          type: string
          description: host name where the keys are
        - name: is_basemirror
          in: query
          required: false
          type: boolean
          description: use this mirror for chroot
        - name: architectures
          in: query
          required: false
          type: array
          description: i386,amd64,arm64,armhf,...
        - name: version
          in: query
          required: false
          type: string
        - name: armored_key_url
          in: query
          required: false
          type: string
        - name: basemirror_id
          in: query
          required: false
          type: string
        - name: download_sources
          in: query
          required: false
          type: boolean
        - name: download_installer
          in: query
          required: false
          type: boolean
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: mirror creation failed.
        "412":
            description: key error.
        "409":
            description: mirror already exists.
        "500":
            description: internal server error.
        "503":
            description: aptly not available.
        "501":
            description: database error occurred.
    """
    params = await request.json()

    mirrorname       = params.get("mirrorname")        # noqa: E221
    mirrorversion    = params.get("mirrorversion")     # noqa: E221
    mirrortype       = params.get("mirrortype")        # noqa: E221
    basemirror       = params.get("basemirror")        # noqa: E221
    mirrorurl        = params.get("mirrorurl")         # noqa: E221
    mirrordist       = params.get("mirrordist")        # noqa: E221
    mirrorcomponents = params.get("mirrorcomponents")  # noqa: E221
    architectures    = params.get("architectures")     # noqa: E221
    mirrorsrc        = params.get("mirrorsrc")         # noqa: E221
    mirrorinst       = params.get("mirrorinst")        # noqa: E221
    mirrorkeytype    = params.get("mirrorkeytype")     # noqa: E221
    mirrorkeyurl     = params.get("mirrorkeyurl")      # noqa: E221
    mirrorkeyids     = params.get("mirrorkeyids")      # noqa: E221
    mirrorkeyserver  = params.get("mirrorkeyserver")   # noqa: E221

    mirrorcomponents = re.split(r"[, ]", mirrorcomponents)

    basemirror_id = None
    if mirrortype == "2":
        base_project, base_version = basemirror.split("/")
        query = request.cirrina.db_session.query(ProjectVersion)
        query = query.join(Project, Project.id == ProjectVersion.project_id)
        query = query.filter(Project.is_mirror.is_(True))
        query = query.filter(Project.name == base_project)
        query = query.filter(ProjectVersion.name == base_version)
        entry = query.first()

        if not entry:
            return ErrorResponse(400, "Invalid basemirror")

        basemirror_id = entry.id

    logger.info("Creating Mirror: %s %s %s %s %s %s %s %s %s %s %s %s %s %s", mirrorname, mirrorversion, mirrortype,
                basemirror, mirrorurl, mirrordist,
                mirrorcomponents, architectures,
                mirrorsrc, mirrorinst, mirrorkeytype,
                mirrorkeyurl, mirrorkeyids, mirrorkeyserver)

    if not mirrorcomponents:
        mirrorcomponents = ["main"]

    is_basemirror = mirrortype == "1"

    if mirrorkeytype == "1":
        mirrorkeyids = []
        mirrorkeyserver = ""
    elif mirrorkeytype == "2":
        mirrorkeyurl = ""
        mirrorkeyids = re.split(r"[, ]", mirrorkeyids)
    else:
        mirrorkeyurl = ""
        mirrorkeyids = []
        mirrorkeyserver = ""

    args = {
        "create_mirror": [
            mirrorname,
            mirrorurl,
            mirrordist,
            mirrorcomponents,
            mirrorkeyids,
            mirrorkeyserver,
            is_basemirror,
            architectures,
            mirrorversion,
            mirrorkeyurl,
            basemirror_id,
            mirrorsrc,
            mirrorinst,
        ]
    }
    logger.info(args)
    await request.cirrina.aptly_queue.put(args)

    return web.Response(status=200, text="Mirror creation started")
