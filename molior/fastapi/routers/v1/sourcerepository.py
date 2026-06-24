"""
/api/repositories
Replaces molior/api/sourcerepository.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["repositories"])


@router.get("/repositories")
def list_repositories(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/repositories/{repository_id}/clone")
def clone_repository(repository_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/repositories/{repository_id}/build")
def build_repository(repository_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError
