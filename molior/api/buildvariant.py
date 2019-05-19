"""
Provides functions to interact with the BuildVariant
database model.
"""
from aiohttp import web

from molior.model.architecture import Architecture
from molior.model.buildvariant import BuildVariant
from molior.model.projectversion import ProjectVersion

from .app import app
from .inputparser import parse_int


@app.http_get("/api/buildvariants")
@app.authenticated
async def get_buildvariant(request):
    """
    Returns all buildvariants releases.
    If arch and basemirror ids are passed
    the matching buildvariant will be returned.
    If a projectversion_id is passed
    the matching buildvariants will be returned.

    ---
    description: Returns a list of buildvariants.
    tags:
        - BuildVariants
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: architecture_id
          in: query
          required: false
          type: integer
        - name: basemirror_id
          in: query
          required: false
          type: integer
        - name: projectversion_id
          in: query
          required: false
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    arch_id = request.GET.getone("architecture_id", None)
    basemirror_id = request.GET.getone("basemirror_id", None)
    projectversion_id = request.GET.getone("projectversion_id", None)

    arch_id = parse_int(arch_id)
    basemirror_id = parse_int(basemirror_id)
    projectversion_id = parse_int(projectversion_id)

    query = request.cirrina.db_session.query(BuildVariant)
    if arch_id and basemirror_id:
        query = (
            query.join(Architecture)
            .filter(Architecture.id == arch_id)
            .filter(BuildVariant.base_mirror_id == basemirror_id)
        )

    if not projectversion_id:
        buildvariants = query.all()
        nb_buildvariants = query.count()
    else:
        project_v = (
            request.cirrina.db_session.query(
                ProjectVersion
            )  # pylint: disable=no-member
            .filter(ProjectVersion.id == projectversion_id)
            .first()
        )
        buildvariants = project_v.buildvariants
        nb_buildvariants = len(buildvariants)

    data = {
        "total_result_count": nb_buildvariants,
        "results": [
            {
                "id": buildvar.id,
                "architecture": buildvar.architecture.name,
                "architecture_id": buildvar.architecture.id,
                "basemirror_id": buildvar.base_mirror.id,
                "basemirror": buildvar.base_mirror.project.name,
                "basemirror_version": buildvar.base_mirror.name,
                "name": buildvar.name,
            }
            for buildvar in buildvariants
        ],
    }

    return web.json_response(data)
