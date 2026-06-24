"""
/api2/build/{build_id}  DELETE + POST abort
Replaces molior/api2/build.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated
from ...db import get_db

router = APIRouter(prefix="/api2", tags=["builds"])


@router.delete("/build/{build_id}")
def delete_build(build_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/build/{build_id}/abort")
def abort_build(build_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.delete("/project/{project_id}/{projectversion_id}/build/{build_id}")
def delete_projectversion_build(
    project_id: str,
    projectversion_id: str,
    build_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError
