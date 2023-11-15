from ..auth import req_role
from molior.model.metadata import MetaData
from molior.model.projectversion import get_projectversion
from molior.tools import OKResponse
from ..app import app


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
