from molior.model.metadata import MetaData
from molior.tools import OKResponse
from ..app import app


@app.http_put("/api2/cleanup")
async def edit_cleanup(request):
    """
    Edit the cleanup configuration.

    ---
    description: Update the cleanup configuration settings.
    tags:
        - AdminConfiguration
    consumes:
        - application/json
    parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                cleanup_active:
                    type: string
                    description: Whether the cleanup is active.
                cleanup_weekdays:
                    type: string
                    description: Comma-separated list of weekdays when cleanup should run.
                cleanup_time:
                    type: string
                    description: Time when the cleanup should run (e.g., "02:00").
    produces:
        - application/json
    responses:
        "200":
            description: Cleanup job is being configured.
        "400":
            description: Invalid input.
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

    return OKResponse("Cleanup job is being configured")


@app.http_get("/api2/cleanup")
async def get_cleanup(request):

    """
    Get the current cleanup configuration.

    ---
    description: Retrieve the current cleanup configuration settings.
    tags:
        - AdminConfiguration
    produces:
        - application/json
    responses:
        "200":
            description: Current cleanup configuration.
        "400":
            description: Error retrieving cleanup configuration.
    """

    db = request.cirrina.db_session

    cleanup_active_metadata = db.query(MetaData).filter_by(name='cleanup_active').first()
    cleanup_time_metadata = db.query(MetaData).filter_by(name='cleanup_time').first()
    cleanup_weekdays_metadata = db.query(MetaData).filter_by(name='cleanup_weekdays').first()

    cleanup_active = cleanup_active_metadata.value if cleanup_active_metadata else None
    cleanup_time = cleanup_time_metadata.value if cleanup_time_metadata else None
    cleanup_weekdays = cleanup_weekdays_metadata.value.split(',') if cleanup_weekdays_metadata else None

    data = {
        'cleanup_active': cleanup_active,
        'cleanup_time': cleanup_time,
        'cleanup_weekdays': cleanup_weekdays
    }
    db.close()

    return OKResponse(data)


@app.http_get("/api2/retention")
async def get_retention(request):

    """
    Get the current retention configuration.

    ---
    description: Retrieve the current retention configuration settings.
    tags:
        - AdminConfiguration
    produces:
        - application/json
    responses:
        "200":
            description: Current retention configuration.
        "400":
            description: Error retrieving retention configuration.
    """

    db = request.cirrina.db_session

    retention_successful_builds_metadata = db.query(MetaData).filter_by(name='retention_successful_builds').first()
    retention_failed_builds_metadata = db.query(MetaData).filter_by(name='retention_failed_builds').first()

    retention_successful_builds = retention_successful_builds_metadata.value if retention_successful_builds_metadata else None
    retention_failed_builds = retention_failed_builds_metadata.value if retention_failed_builds_metadata else None

    data = {
        'retention_successful_builds': retention_successful_builds,
        'retention_failed_builds': retention_failed_builds,
    }
    db.close()

    return OKResponse(data)


@app.http_put("/api2/retention")
async def edit_retention(request):

    """
    Edit the retention configuration.

    ---
    description: Update the retention configuration settings.
    tags:
        - AdminConfiguration
    consumes:
        - application/json
    parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                retention_successful_builds:
                    type: integer
                    description: Retention policy for successful builds.
                retention_failed_builds:
                    type: integer
                    description: Retention policy for failed builds.
    produces:
        - application/json
    responses:
        "200":
            description: Package Retention is being configured.
        "400":
            description: Invalid input.
    """

    params = await request.json()
    retention_successful_builds = params.get("retention_successful_builds")
    retention_failed_builds = params.get("retention_failed_builds")

    db = request.cirrina.db_session

    existing_retention_successful_builds_metadata = db.query(MetaData).filter_by(name='retention_successful_builds').first()
    if existing_retention_successful_builds_metadata:
        existing_retention_successful_builds_metadata.value = retention_successful_builds
    else:
        db.add(MetaData(name='retention_successful_builds', value=retention_successful_builds))

    existing_retention_failed_builds_metadata = db.query(MetaData).filter_by(name='retention_failed_builds').first()
    if existing_retention_failed_builds_metadata:
        existing_retention_failed_builds_metadata.value = retention_failed_builds
    else:
        db.add(MetaData(name='retention_failed_builds', value=retention_failed_builds))

    db.commit()

    return OKResponse("Package Retention is being configured")


@app.http_get("/api2/maintenance")
async def get_maintenance(request):

    """
    Get the current maintenance configuration.

    ---
    description: Retrieve the current maintenance mode and message.
    tags:
        - AdminConfiguration
    produces:
        - application/json
    responses:
        "200":
            description: Current maintenance configuration.
        "400":
            description: Error retrieving maintenance configuration.
    """

    db = request.cirrina.db_session

    maintenance_mode_metadata = db.query(MetaData).filter_by(name='maintenance_mode').first()
    maintenance_message_metadata = db.query(MetaData).filter_by(name='maintenance_message').first()

    maintenance_mode = maintenance_mode_metadata.value if maintenance_mode_metadata else None
    maintenance_message = maintenance_message_metadata.value if maintenance_message_metadata else None

    data = {
        'maintenance_mode': maintenance_mode,
        'maintenance_message': maintenance_message,
    }
    db.close()

    return OKResponse(data)


@app.http_put("/api2/maintenance")
async def edit_maintenance(request):

    """
    Edit the maintenance configuration.

    ---
    description: Update the maintenance mode and message.
    tags:
        - AdminConfiguration
    consumes:
        - application/json
    parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                maintenance_mode:
                    type: string
                    description: The maintenance mode status.
                maintenance_message:
                    type: string
                    description: The maintenance message.
    produces:
        - application/json
    responses:
        "200":
            description: Maintenance details are being changed.
            content:
                application/json:
                    schema:
                        type: string
        "400":
            description: Invalid input.
            content:
                application/json:
                    schema:
                        type: string
    """

    params = await request.json()
    maintenance_mode = params.get("maintenance_mode")
    maintenance_message = params.get("maintenance_message")

    db = request.cirrina.db_session

    existing_maintenance_mode = db.query(MetaData).filter_by(name='maintenance_mode').first()
    if existing_maintenance_mode:
        existing_maintenance_mode.value = str(maintenance_mode)
    else:
        db.add(MetaData(name='maintenance_mode', value=str(maintenance_mode)))

    existing_maintenance_message = db.query(MetaData).filter_by(name='maintenance_message').first()
    if existing_maintenance_message:
        existing_maintenance_message.value = maintenance_message
    else:
        db.add(MetaData(name='maintenance_message', value=maintenance_message))

    db.commit()

    return OKResponse("Maintenance details are being changed")
