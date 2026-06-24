"""
/api2/cleanup, /api2/retention, /api2/maintenance
Replaces molior/api2/admin.py

Fixed: original endpoints had no auth. Now protected with require_admin.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import CurrentUser, require_admin
from ...db import get_db
from ....model.metadata import MetaData

router = APIRouter(prefix="/api2", tags=["admin"])


def _upsert(db: Session, name: str, value):
    row = db.query(MetaData).filter_by(name=name).first()
    if row:
        row.value = str(value) if value is not None else None
    else:
        db.add(MetaData(name=name, value=str(value) if value is not None else None))


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class CleanupBody(BaseModel):
    cleanup_active: Optional[str] = None
    cleanup_weekdays: Optional[str] = None
    cleanup_time: Optional[str] = None


@router.get("/cleanup")
def get_cleanup(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    active = db.query(MetaData).filter_by(name="cleanup_active").first()
    time_ = db.query(MetaData).filter_by(name="cleanup_time").first()
    weekdays = db.query(MetaData).filter_by(name="cleanup_weekdays").first()
    return {
        "cleanup_active": active.value if active else None,
        "cleanup_time": time_.value if time_ else None,
        "cleanup_weekdays": weekdays.value.split(",") if weekdays else None,
    }


@router.put("/cleanup")
def set_cleanup(
    body: CleanupBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _upsert(db, "cleanup_active", body.cleanup_active)
    _upsert(db, "cleanup_weekdays", body.cleanup_weekdays)
    _upsert(db, "cleanup_time", body.cleanup_time)
    db.commit()
    return "Cleanup job is being configured"


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

class RetentionBody(BaseModel):
    retention_successful_builds: Optional[int] = None
    retention_failed_builds: Optional[int] = None


@router.get("/retention")
def get_retention(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    successful = db.query(MetaData).filter_by(name="retention_successful_builds").first()
    failed = db.query(MetaData).filter_by(name="retention_failed_builds").first()
    return {
        "retention_successful_builds": successful.value if successful else None,
        "retention_failed_builds": failed.value if failed else None,
    }


@router.put("/retention")
def set_retention(
    body: RetentionBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _upsert(db, "retention_successful_builds", body.retention_successful_builds)
    _upsert(db, "retention_failed_builds", body.retention_failed_builds)
    db.commit()
    return "Package Retention is being configured"


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

class MaintenanceBody(BaseModel):
    maintenance_mode: Optional[str] = None
    maintenance_message: Optional[str] = None


@router.get("/maintenance")
def get_maintenance(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    mode = db.query(MetaData).filter_by(name="maintenance_mode").first()
    msg = db.query(MetaData).filter_by(name="maintenance_message").first()
    return {
        "maintenance_mode": mode.value if mode else None,
        "maintenance_message": msg.value if msg else None,
    }


@router.put("/maintenance")
def set_maintenance(
    body: MaintenanceBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _upsert(db, "maintenance_mode", body.maintenance_mode)
    _upsert(db, "maintenance_message", body.maintenance_message)
    db.commit()
    return "Maintenance details are being changed"
