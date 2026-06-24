"""
/api/mirror, /api/mirrors, /api/mirror/{id}
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams
from ....model.mirrorkey import MirrorKey
from ....model.project import Project
from ....model.projectversion import ProjectVersion
from ....molior.queues import enqueue_aptly
from ....tools import db2array, escape_for_like

router = APIRouter(tags=["mirrors"])


def _mirror_data(mirror, db):
    mirrorkey = db.query(MirrorKey).filter_by(projectversion_id=mirror.id).first()
    mirrorkeyurl = mirrorkeyids = mirrorkeyserver = ""
    if mirrorkey:
        mirrorkeyurl = mirrorkey.keyurl or ""
        mirrorkeyids = " ".join(db2array(mirrorkey.keyids)) if mirrorkey.keyids else ""
        mirrorkeyserver = mirrorkey.keyserver or ""

    base_mirror_id = -1
    base_mirror_url = base_mirror_name = ""
    if not mirror.project.is_basemirror and mirror.basemirror:
        base_mirror_id = mirror.basemirror.id
        base_mirror_url = mirror.basemirror.get_apt_repo(url_only=True)
        base_mirror_name = f"{mirror.basemirror.project.name}/{mirror.basemirror.name}"

    return {
        "id": mirror.id,
        "name": mirror.project.name,
        "version": mirror.name,
        "url": mirror.mirror_url,
        "basemirror_id": base_mirror_id,
        "basemirror_url": base_mirror_url,
        "basemirror_name": base_mirror_name,
        "distribution": mirror.mirror_distribution,
        "components": mirror.mirror_components,
        "is_basemirror": mirror.project.is_basemirror,
        "architectures": db2array(mirror.mirror_architectures),
        "is_locked": mirror.is_locked,
        "with_sources": mirror.mirror_with_sources,
        "with_installer": mirror.mirror_with_installer,
        "project_id": mirror.project.id,
        "state": mirror.mirror_state,
        "apt_url": mirror.get_apt_repo(url_only=True),
        "mirrorkeyurl": mirrorkeyurl,
        "mirrorkeyids": mirrorkeyids,
        "mirrorkeyserver": mirrorkeyserver,
        "external_repo": mirror.external_repo,
        "dependency_policy": mirror.dependency_policy,
        "mirrorfilter": mirror.mirror_filter,
    }


@router.get("/api/mirror")
@router.get("/api/mirrors")
def get_mirrors(
    q: Optional[str] = Query(default=""),
    basemirror: Optional[bool] = Query(default=False),
    is_basemirror: Optional[bool] = Query(default=False),
    q_basemirror: Optional[str] = Query(default=""),
    url: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(ProjectVersion).join(Project).filter(
        Project.is_mirror.is_(True), ProjectVersion.is_deleted.is_(False)
    )

    if q:
        for term in re.split("[/ ]", q):
            if term:
                term = escape_for_like(term)
                query = query.filter(or_(
                    Project.name.ilike(f"%{term}%"),
                    ProjectVersion.name.ilike(f"%{term}%"),
                ))

    if q_basemirror:
        bm_query = db.query(ProjectVersion).join(Project).filter(
            Project.is_basemirror.is_(True), ProjectVersion.is_deleted.is_(False)
        )
        for term in re.split("[/ ]", q_basemirror):
            if term:
                bm_query = bm_query.filter(or_(
                    Project.name.ilike(f"%{term}%"),
                    ProjectVersion.name.ilike(f"%{term}%"),
                ))
        bm_ids = [b.id for b in bm_query.all()]
        query = query.filter(ProjectVersion.basemirror_id.in_(bm_ids))

    if url:
        query = query.filter(ProjectVersion.mirror_url.ilike(f"%{url}%"))
    if basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True))

    query = query.order_by(func.lower(Project.name), func.lower(ProjectVersion.name).desc())
    total = query.count()
    results = pagination.apply(query).all()
    return {"total_result_count": total, "results": [_mirror_data(m, db) for m in results]}


@router.put("/api/mirror/{id}")
@router.post("/api/mirror/{id}/update")
async def update_mirror(
    id: int,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mirror = db.query(ProjectVersion).filter(ProjectVersion.id == id).first()
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")
    if mirror.is_locked:
        raise HTTPException(status_code=400, detail="Mirror is locked")
    if mirror.mirror_state not in ("error", "init_error", "new"):
        raise HTTPException(status_code=400, detail="Mirror not in error state")

    if mirror.mirror_state in ("new", "init_error"):
        await enqueue_aptly({"init_mirror": [mirror.id]})
    else:
        await enqueue_aptly({"update_mirror": [mirror.id]})
    return "Successfully started update on mirror"
