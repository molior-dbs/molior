"""
/api2/cleanup, /api2/retention, /api2/maintenance
Replaces molior/api2/admin.py

NOTE: original endpoints have no auth — fixed here with require_admin
(see API-Analysis observation #2).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, require_admin
from ...db import get_db

router = APIRouter(prefix="/api2", tags=["admin"])


@router.get("/cleanup")
def get_cleanup(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/cleanup")
def set_cleanup(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/retention")
def get_retention(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/retention")
def set_retention(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/maintenance")
def get_maintenance(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/maintenance")
def set_maintenance(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError
