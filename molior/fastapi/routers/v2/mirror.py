"""
/api2/mirror
Replaces molior/api2/mirror.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api2", tags=["mirrors"])


@router.get("/mirror/{name}/{version}")
def get_mirror(name: str, version: str, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/mirror/{name}/{version}/dependents")
def get_mirror_dependents(
    name: str,
    version: str,
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/mirror/{name}/{version}/aptsources")
def get_mirror_aptsources(name: str, version: str, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/mirror")
def create_mirror(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/mirror/{name}/{version}")
def update_mirror(name: str, version: str, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.delete("/mirror/{name}/{version}")
def delete_mirror(name: str, version: str, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError
