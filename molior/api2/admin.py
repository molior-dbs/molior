from ..auth import req_role
from molior.model.metadata import MetaData
from molior.tools import OKResponse
from ..app import app
from ..logger import logger


@app.http_put("/api2/cleanup")
async def edit_cleanup(request):

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

@app.http_get("/api2/maintenance")
async def get_maintenance(request):

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
