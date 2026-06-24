"""
/api/projects/{project_id}/users
Replaces molior/api/projectuserrole.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/projects/{project_id}/users")
def list_project_users(
    project_id: str,
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/projects/{project_id}/users/{user_id}")
def get_project_user_role(
    project_id: str,
    user_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/projects/{project_id}/users/{user_id}")
def set_project_user_role(
    project_id: str,
    user_id: int,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/projects/{project_id}/users/{user_id}")
def remove_project_user_role(
    project_id: str,
    user_id: int,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError
