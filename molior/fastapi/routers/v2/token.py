"""
/api2/tokens
Replaces molior/api2/token.py
"""

import hashlib
from secrets import token_hex
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams
from ....model.authtoken import Authtoken
from ....model.authtoken_project import Authtoken_Project
from ....tools import array2db

router = APIRouter(prefix="/api2", tags=["tokens"])


@router.get("/tokens")
def list_tokens(
    description: Optional[str] = Query(default=""),
    exclude_project_id: Optional[int] = Query(default=None),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(Authtoken)
    if exclude_project_id:
        query = query.outerjoin(Authtoken_Project)
        query = query.filter(
            or_(
                Authtoken_Project.project_id != exclude_project_id,
                Authtoken_Project.project_id.is_(None),
            )
        )
    if description:
        query = query.filter(Authtoken.description.ilike("%{}%".format(description)))
    total = query.count()
    tokens = pagination.apply(query).all()
    return {
        "total_result_count": total,
        "results": [{"id": t.id, "description": t.description} for t in tokens],
    }


class CreateTokenBody(BaseModel):
    description: Optional[str] = None


@router.post("/tokens")
def create_token(
    body: CreateTokenBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raw = token_hex(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    token = Authtoken(
        description=body.description,
        token=hashed,
        roles=array2db(["project_create", "mirror_create"]),
    )
    db.add(token)
    db.commit()
    return {"token": raw}


class DeleteTokenBody(BaseModel):
    id: int


@router.delete("/tokens")
def delete_token(
    body: DeleteTokenBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    mappings = db.query(Authtoken_Project).filter(
        Authtoken_Project.authtoken_id == body.id
    ).all()
    for m in mappings:
        db.delete(m)

    token = db.query(Authtoken).filter(Authtoken.id == body.id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    db.delete(token)
    db.commit()
    return ""
