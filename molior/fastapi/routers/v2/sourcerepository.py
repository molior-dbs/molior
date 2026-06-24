"""
/api2/repository, /api2/repositories
Replaces molior/api2/sourcerepository.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api2", tags=["repositories"])


@router.get("/repository/{repository_id}")
def get_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/repository/{repository_id}/dependents")
def get_repository_dependents(
    repository_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/repositories")
def list_repositories(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/repository/{repository_id}/merge")
def merge_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/repository/{repository_id}")
def delete_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/repository/{repository_id}")
def update_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raise NotImplementedError
