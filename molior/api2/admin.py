from molior import app
from molior.auth.auth import req_role
from molior.model.metadata import MetaData
from molior.model.projectversion import get_projectversion
from molior.tools import OKResponse


@app.http_put("/api2/cleanup")
@req_role("admin")
async def edit_cleanup(request):
    """
    Modify the weekly cleanup configuration

    ---
    description: Modify a project version
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: string
        - name: projectversion_id
          in: path
          required: true
          type: string
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                description:
                    type: string
                    example: "This version does this and that"
                dependency_policy:
                    type: string
                    description: Dependency policy
                    example: strict
                retention_successful_builds:
                    type: integer
                retention_failed_builds:
                    type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    params = await request.json()
    cleanup_active = params.get("cleanup_active")
    cleanup_weekdays = params.get("cleanup_weekdays")
    cleanup_time = params.get("cleanup_time")

    db = request.cirrina.db_session

    existing_active_metadata = db.query(MetaData).filter_by(name='cleanup_active').first()
    if existing_active_metadata:
        existing_active_metadata.value = str(cleanup_active)
    else:
        db.add(MetaData(name='cleanup_active', value=str(cleanup_active)))

    existing_weekdays_metadata = db.query(MetaData).filter_by(name='cleanup_weekdays').first()
    if existing_weekdays_metadata:
        existing_weekdays_metadata.value = cleanup_weekdays
    else:
        db.add(MetaData(name='cleanup_weekdays', value=cleanup_weekdays))

    existing_time_metadata = db.query(MetaData).filter_by(name='cleanup_time').first()
    if existing_time_metadata:
        existing_time_metadata.value = cleanup_time
    else:
        db.add(MetaData(name='cleanup_time', value=cleanup_time))

    db.commit()

    return OKResponse({"id": MetaData.id, "name": MetaData.name})
