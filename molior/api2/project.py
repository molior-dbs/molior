from ..app import app
from ..model.project import Project
from ..tools import ErrorResponse, OKResponse


@app.http_get("/api2/project/{project_name}")
@app.authenticated
async def get_project_byname(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_name
          in: path
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

    project_name = request.match_info["project_name"]

    project = request.cirrina.db_session.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project with name {} could not be found!".format(project_name))

    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
    }

    return OKResponse(data)
