"""
/api/projects/{project_id}/users, /api/projects/{project_id}/users/{user_id}
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams
from ...ws import broadcast
from ....model.project import Project
from ....model.user import User
from ....model.userrole import UserRole, USER_ROLES
from ....molior.notifier import Subject, Event

router = APIRouter(tags=["projectuserroles"])


@router.get("/api/projects/{project_id}/users")
def get_project_users(
    project_id: int,
    filter_name: Optional[str] = Query(default=""),
    filter_role: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = (
        db.query(UserRole).filter_by(project_id=project_id)
        .join(User).filter(UserRole.user_id == User.id)
        .join(Project).filter(UserRole.project_id == Project.id)
        .order_by(User.username)
    )
    if filter_name:
        query = query.filter(User.username.ilike(f"%{filter_name}%"))
    if filter_role:
        for r in USER_ROLES:
            if filter_role.lower() in r:
                query = query.filter(UserRole.role == r)
                break

    total = query.count()
    roles = pagination.apply(query).all()
    return {
        "project_name": project.name, "project_id": project.id,
        "total_result_count": total,
        "results": [{"id": r.user.id, "username": r.user.username, "role": r.role} for r in roles],
    }


@router.get("/api/projects/{project_id}/users/{user_id}")
def get_project_userrole(
    project_id: int,
    user_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if user_id == -1:
        user = db.query(User).filter(User.username == current_user.username).first()
    else:
        user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rolerec = db.query(UserRole).filter_by(project=project, user=user).first()
    return {"role": rolerec.role if rolerec else None}


class UpsertRoleBody(BaseModel):
    role: Optional[str] = "member"


@router.put("/api/projects/{project_id}/users/{user_id}")
async def upsert_project_user_role(
    project_id: int,
    user_id: int,
    body: UpsertRoleBody,
    _: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rolerec = db.query(UserRole).filter_by(project_id=project.id, user_id=user.id).first()
    if rolerec:
        rolerec.role = body.role
    else:
        db.add(UserRole(user_id=user_id, project_id=project_id, role=body.role))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    await broadcast({
        "event": Event.changed.value, "subject": Subject.userrole.value,
        "changed": {"id": user_id, "project_id": project_id, "role": body.role},
    })
    return {"result": f"{user.username} is now {body.role} on {project.name}"}


@router.delete("/api/projects/{project_id}/users/{user_id}")
async def remove_project_user(
    project_id: int,
    user_id: int,
    _: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rolerec = db.query(UserRole).filter_by(project_id=project.id, user_id=user.id).first()
    if not rolerec:
        raise HTTPException(status_code=400, detail="No role to delete")

    db.query(UserRole).filter_by(project_id=project.id, user_id=user.id).delete()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    await broadcast({
        "event": Event.removed.value, "subject": Subject.userrole.value,
        "changed": {"id": user_id, "project_id": project_id},
    })
    return {"result": f"{user.username} is removed from {project.name}"}
