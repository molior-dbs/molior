"""
/api/projectversions
Replaces molior/api/projectversion.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["projectversions"])


@router.get("/projectversions")
def list_projectversions(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/projectversions/{projectversion_id}/toggleci")
def toggle_ci(projectversion_id: str, current_user: CurrentUser = Depends(require_role("owner")), db: Session = Depends(get_db)):
    raise NotImplementedError
