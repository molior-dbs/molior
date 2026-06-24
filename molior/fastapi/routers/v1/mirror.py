"""
/api/mirror, /api/mirrors, /api/mirror/{id}/update
Replaces molior/api/mirror.py
"""

from fastapi import APIRouter, Depends

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api", tags=["mirrors"])


@router.get("/mirrors")
@router.get("/mirror")
def list_mirrors(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    # TODO: port from molior/api/mirror.py
    raise NotImplementedError


@router.post("/mirror/{mirror_id}/update")
@router.put("/mirror/{mirror_id}")
def update_mirror(mirror_id: int, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    # TODO: port from molior/api/mirror.py
    raise NotImplementedError
