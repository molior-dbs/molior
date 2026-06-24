"""
/api/repositories, /api/repositories/{id}/clone, /api/repositories/{id}/build
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated
from ...db import get_db
from ...responses import PaginationParams
from ....model.build import Build
from ....model.buildtask import BuildTask
from ....model.projectversion import ProjectVersion
from ....model.sourcerepository import SourceRepository
from ....model.sourepprover import SouRepProVer
from ....molior.queues import enqueue_task
from ....tools import db2array

router = APIRouter(tags=["repositories"])


@router.get("/api/repositories")
def get_repositories(
    q: Optional[str] = Query(default=None),
    distinct: Optional[str] = Query(default=None),
    project_version_id: Optional[int] = Query(default=None),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    # q is a JSON filter object: {"name": "...", "url": "..."}
    try:
        q_filter = json.loads(q) if q else None
    except (ValueError, TypeError):
        q_filter = None

    try:
        distinct_fields = json.loads(distinct) if distinct else []
    except (ValueError, TypeError):
        distinct_fields = []

    repos = db.query(SourceRepository)

    if project_version_id:
        repos = repos.filter(SourceRepository.projectversions.any(id=project_version_id))

    if q_filter:
        name = q_filter.get("name")
        if name:
            repos = repos.filter(SourceRepository.url.ilike(f"%/{name}%.git"))
        url = q_filter.get("url")
        if url:
            repos = repos.filter(SourceRepository.url.ilike(f"%{url}%"))

    if "url" in distinct_fields:
        repos = repos.distinct(SourceRepository.url)

    total = repos.count()
    repos = repos.order_by(SourceRepository.name)
    results_page = pagination.apply(repos).all()

    projectversion = None
    if project_version_id:
        projectversion = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()

    results = []
    for repo in results_page:
        entry = {
            "id": repo.id, "name": repo.name, "url": repo.url, "state": repo.state,
            "dependencies": [],
        }
        if projectversion:
            build = db.query(Build).filter(
                Build.sourcerepository_id == repo.id,
                Build.projectversion_id == projectversion.id,
                Build.buildtype == "deb",
            ).order_by(Build.id.desc()).first()
            srpv = db.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == repo.id,
                SouRepProVer.projectversion_id == projectversion.id,
            ).first()
            last_build = db.query(Build).filter(
                Build.sourcerepository_id == repo.id,
                Build.buildtype == "source",
            ).order_by(Build.id.desc()).first()
            entry["projectversion"] = {
                "id": projectversion.id,
                "name": projectversion.project.name,
                "version": projectversion.name,
                "last_gitref": last_build.git_ref if last_build else None,
                "architectures": db2array(srpv.architectures) if srpv else [],
                "last_build": {"id": build.id, "version": build.version, "buildstate": build.buildstate} if build else None,
            }
        else:
            entry["projectversions"] = [
                {"id": pv.id, "name": pv.project.name, "version": pv.name}
                for pv in repo.projectversions
            ]
        results.append(entry)

    return {"total_result_count": total, "results": results}


@router.post("/api/repositories/{repository_id}/clone")
async def trigger_clone(
    repository_id: int,
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    repo = db.query(SourceRepository).filter(SourceRepository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=400, detail="Repository not found")
    if repo.state != "error":
        raise HTTPException(status_code=400, detail="Repository not in error state")

    build = Build(
        version=None, git_ref=None, ci_branch=None, is_ci=None,
        sourcename=repo.name, buildstate="new", buildtype="build",
        sourcerepository=repo, maintainer=None,
    )
    db.add(build)
    await build.build_added()

    token = uuid.uuid4()
    db.add(BuildTask(build=build, task_id=str(token)))
    db.commit()

    await enqueue_task({"clone": [build.id, repo.id]})
    return "Clone job started"


@router.post("/api/repositories/{repository_id}/build")
async def trigger_build(
    repository_id: int,
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    repo = db.query(SourceRepository).filter(SourceRepository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=400, detail="Repository not found")

    build = Build(
        version=None, git_ref=None, ci_branch=None, is_ci=None,
        sourcename=repo.name, buildstate="new", buildtype="build",
        sourcerepository=repo, maintainer=None,
    )
    db.add(build)
    db.commit()
    await build.build_added()

    token = uuid.uuid4()
    db.add(BuildTask(build=build, task_id=str(token)))
    db.commit()

    await enqueue_task({"buildlatest": [repository_id, build.id]})
    return {"build_token": str(token)}
