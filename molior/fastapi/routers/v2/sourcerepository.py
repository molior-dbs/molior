"""
/api2/repository, /api2/repositories
Replaces molior/api2/sourcerepository.py
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams
from ....model.build import Build
from ....model.projectversion import ProjectVersion
from ....model.sourcerepository import SourceRepository
from ....model.sourepprover import SouRepProVer
from ....molior.queues import enqueue_task

router = APIRouter(prefix="/api2", tags=["repositories"])


@router.get("/repository/{repository_id}")
def get_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    repo = db.query(SourceRepository).filter_by(id=repository_id).first()
    if not repo:
        raise HTTPException(status_code=404,
                            detail=f"Repository with id {repository_id} not found")
    return {"id": repo.id, "name": repo.name, "url": repo.url, "state": repo.state}


@router.get("/repository/{repository_id}/dependents")
def get_repository_dependents(
    repository_id: int,
    q: Optional[str] = Query(default=""),
    unlocked: Optional[bool] = Query(default=False),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    repo = db.query(SourceRepository).filter_by(id=repository_id).first()
    if not repo:
        raise HTTPException(status_code=404,
                            detail=f"Repository with id {repository_id} not found")

    query = db.query(ProjectVersion).filter(
        SouRepProVer.projectversion_id == ProjectVersion.id,
        SouRepProVer.sourcerepository_id == repo.id,
    )
    if q:
        query = query.filter(ProjectVersion.fullname.ilike(f"%{q}%"))
    if unlocked:
        query = query.filter(ProjectVersion.is_locked.is_(False))
    query = query.order_by(ProjectVersion.fullname)
    total = query.count()
    results = pagination.apply(query).all()
    return {"total_result_count": total, "results": [pv.data() for pv in results]}


@router.get("/repositories")
def list_repositories(
    filter_url: Optional[str] = Query(default=""),
    q: Optional[str] = Query(default=""),
    exclude_projectversion_id: Optional[int] = Query(default=None),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(SourceRepository)

    if filter_url:
        for term in re.split("[/ ]", filter_url):
            if term:
                query = query.filter(SourceRepository.url.ilike(f"%{term}%"))

    if q:
        query = query.filter(SourceRepository.name.ilike(f"%{q}%"))

    if exclude_projectversion_id is not None:
        query = query.filter(
            ~SourceRepository.projectversions.any(
                ProjectVersion.id == exclude_projectversion_id
            )
        )

    query = query.order_by(SourceRepository.name)
    total = query.count()
    results = pagination.apply(query).all()
    return {
        "total_result_count": total,
        "results": [
            {"id": r.id, "name": r.name, "url": r.url, "state": r.state}
            for r in results
        ],
    }


class MergeBody(BaseModel):
    duplicate: int


@router.put("/repository/{repository_id}/merge")
async def merge_repository(
    repository_id: int,
    body: MergeBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    await enqueue_task({"merge_duplicate_repo": [repository_id, body.duplicate]})
    return "SourceRepository changed"


@router.delete("/repository/{repository_id}")
async def delete_repository(
    repository_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repo = db.query(SourceRepository).filter(
        SourceRepository.id == repository_id
    ).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    builds = db.query(Build).filter(Build.sourcerepository_id == repository_id).all()
    if repo.projectversions:
        raise HTTPException(status_code=400,
                            detail="Repository cannot be deleted: used by projects")
    if builds:
        raise HTTPException(status_code=400,
                            detail="Repository cannot be deleted: builds exist")

    await enqueue_task({"delete_repo": [repository_id]})
    return "Repository deleted"


class EditRepositoryBody(BaseModel):
    url: str


@router.put("/repository/{repository_id}")
async def update_repository(
    repository_id: int,
    body: EditRepositoryBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not body.url:
        raise HTTPException(status_code=400, detail="No URL received")

    repo = db.query(SourceRepository).filter(
        SourceRepository.id == repository_id
    ).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.url != body.url:
        await enqueue_task({"repo_change_url": [repository_id, body.url]})
    return "Repository changed"
