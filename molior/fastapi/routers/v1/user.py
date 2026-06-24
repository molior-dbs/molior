"""
/api/users, /api/user/{user_id}
Replaces molior/api/user.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users")
def list_users(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/users")
def create_user(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/users/{user_id}")
@router.put("/user/{user_id}")
def update_user(user_id: int, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.delete("/users/{user_id}")
@router.delete("/user/{user_id}")
def delete_user(user_id: int, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/users/{user_id}/roles")
def get_user_roles(user_id: int, current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError
