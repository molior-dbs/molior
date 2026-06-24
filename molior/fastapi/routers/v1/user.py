"""
/api/users, /api/user/{id}
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams
from ....auth.auth import Auth
from ....model.project import Project
from ....model.user import User
from ....model.userrole import UserRole

router = APIRouter(tags=["users"])


@router.get("/api/users")
def get_users(
    name: Optional[str] = Query(default=""),
    email: Optional[str] = Query(default=""),
    admin: Optional[str] = Query(default="false"),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if admin.lower() == "true":
        query = query.filter(User.is_admin.is_(True))
    if name:
        query = query.filter(User.username.ilike(f"%{name}%"))
    if email:
        query = query.filter(User.email.ilike(f"%{email}%"))
    query = query.order_by(User.username)
    total = query.count()
    users = pagination.apply(query).all()
    return {
        "total_result_count": total,
        "results": [{"id": u.id, "username": u.username, "email": u.email, "is_admin": u.is_admin} for u in users],
    }


class CreateUserBody(BaseModel):
    name: str
    email: str
    password: str
    is_admin: Optional[bool] = False


@router.post("/api/users")
def create_user(
    body: CreateUserBody,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not body.name:
        raise HTTPException(status_code=400, detail="Invalid username")
    if not body.email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if not body.password:
        raise HTTPException(status_code=400, detail="Invalid password")
    try:
        Auth().add_user(body.name, body.password, body.email, body.is_admin)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {}


class EditUserBody(BaseModel):
    is_admin: Optional[bool] = None
    email: Optional[str] = None
    password: Optional[str] = None


@router.put("/api/users/{user_id}")
@router.put("/api/user/{user_id}")
def update_user(
    user_id: int,
    body: EditUserBody,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not Auth().edit_user(user_id, body.password, body.email, body.is_admin):
        raise HTTPException(status_code=400, detail="Error modifying user")
    return {}


@router.delete("/api/users/{user_id}")
@router.delete("/api/user/{user_id}")
def delete_user(
    user_id: int,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not Auth().delete_user(user_id):
        raise HTTPException(status_code=400, detail="Error deleting user")
    return {}


@router.get("/api/users/{user_id}/roles")
def get_user_roles(
    user_id: int,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = {
        "username": user.username, "user_id": user.id,
        "roles": {"owner": [], "member": [], "manager": []},
    }
    roles = db.query(UserRole).filter_by(user_id=user_id).join(Project).filter(
        UserRole.project_id == Project.id
    ).order_by(Project.name).values(UserRole.role, Project.id, Project.name)

    for role in roles:
        data["roles"][role.role].append({"id": role.id, "name": role.name})

    return data
