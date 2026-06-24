"""
/api/projectversions, /api/projectversions/{id}/toggleci
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams
from ....logger import logger
from ....model.project import Project
from ....model.projectversion import ProjectVersion
from ....tools import escape_for_like, parse_int

router = APIRouter(tags=["projectversions"])


@router.get("/api/projectversions")
def get_projectversions(
    project_id: Optional[str] = Query(default=None),
    project_name: Optional[str] = Query(default=None),
    exclude_id: Optional[str] = Query(default=None),
    basemirror_id: Optional[str] = Query(default=None),
    isbasemirror: Optional[bool] = Query(default=False),
    dependant_id: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(ProjectVersion).join(Project).filter(ProjectVersion.is_deleted.is_(False))

    _exclude_id = parse_int(exclude_id)
    if _exclude_id:
        query = query.filter(Project.id != _exclude_id)

    _project_id = parse_int(project_id)
    if _project_id:
        query = query.filter(Project.id == _project_id)

    if project_name:
        query = query.filter(func.lower(Project.name) == project_name.lower())

    if q:
        for term in re.split("[/ ]", q):
            if term:
                term = escape_for_like(term)
                query = query.filter(or_(
                    Project.name.ilike(f"%{term}%"),
                    ProjectVersion.name.ilike(f"%{term}%"),
                ))

    _basemirror_id = parse_int(basemirror_id)
    if _basemirror_id:
        query = query.filter(ProjectVersion.basemirror_id == _basemirror_id)
    elif isbasemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")
    else:
        query = query.filter(Project.is_mirror.is_(False))

    _dependant_id = parse_int(dependant_id)
    if _dependant_id:
        pv = db.query(ProjectVersion).filter(ProjectVersion.id == _dependant_id).first()
        pvs = [pv.basemirror] if pv else []
        return {"total_result_count": len(pvs), "results": [p.data() for p in pvs if p]}

    query = query.order_by(func.lower(Project.name), func.lower(ProjectVersion.name))
    total = query.count()
    results = pagination.apply(query).all()
    return {"total_result_count": total, "results": [pv.data() for pv in results]}


@router.post("/api/projectversions/{projectversion_id}/toggleci")
def toggle_ci(
    projectversion_id: int,
    _: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not pv:
        raise HTTPException(status_code=400, detail=f"Projectversion {projectversion_id} not found")

    pv.ci_builds_enabled = not pv.ci_builds_enabled
    db.commit()

    result = "enabled" if pv.ci_builds_enabled else "disabled"
    logger.info("CI builds %s on ProjectVersion '%s/%s'", result, pv.project.name, pv.name)
    return f"Ci builds are now {result}."
