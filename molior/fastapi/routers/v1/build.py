"""
/api/builds, /api/build/{build_id}, /api/build (POST)
"""

import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import or_

from ...auth import CurrentUser, authenticated
from ...db import get_db
from ...responses import PaginationParams
from ....model.build import Build, BUILD_STATES
from ....model.maintainer import Maintainer
from ....model.project import Project
from ....model.projectversion import ProjectVersion
from ....model.sourcerepository import SourceRepository
from ....molior.queues import enqueue_task

router = APIRouter(tags=["builds"])


@router.get("/api/builds")
def get_builds(
    _: CurrentUser = Depends(authenticated),
    search: Optional[str] = Query(default=None),
    search_project: Optional[str] = Query(default=None),
    project: Optional[str] = Query(default=None),
    maintainer: Optional[str] = Query(default=None),
    commit: Optional[str] = Query(default=None),
    architecture: Optional[str] = Query(default=None),
    distrelease: Optional[str] = Query(default=None),
    version: Optional[str] = Query(default=None),
    sourcerepository: Optional[str] = Query(default=None),
    startstamp: Optional[str] = Query(default=None),
    buildstate: Optional[List[str]] = Query(default=None),
    project_version_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    sourcerepository_id: Optional[int] = Query(default=None),
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    builds = db.query(Build).outerjoin(Build.maintainer)
    builds = builds.filter(Build.is_deleted.is_(False))

    if sourcerepository_id:
        builds = builds.filter(Build.sourcerepository_id == sourcerepository_id)
    if project_version_id:
        builds = builds.filter(Build.projectversion_id == project_version_id)
    if project_id:
        builds = builds.join(ProjectVersion).join(Project).filter(Project.id == project_id)

    if from_:
        try:
            builds = builds.filter(Build.startstamp > datetime.strptime(from_, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
    if to:
        try:
            builds = builds.filter(Build.startstamp < datetime.strptime(to, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass

    if distrelease:
        builds = builds.filter(Project.name.ilike(f"%{distrelease}%"))

    if search:
        for term in re.split("[/ ]", search):
            if term:
                builds = builds.filter(or_(
                    Build.sourcename.ilike(f"%{term}%"),
                    Build.version.ilike(f"%{term}%"),
                    Build.architecture.ilike(f"%{term}%"),
                ))

    if search_project:
        builds = builds.join(ProjectVersion, isouter=True).join(Project, isouter=True)
        for term in re.split("[/ ]", search_project):
            if term:
                builds = builds.filter(Project.is_mirror.is_(False), or_(
                    ProjectVersion.name.ilike(f"%{term}%"),
                    Project.name.ilike(f"%{term}%"),
                ))

    projectversion = None
    if project:
        if "/" not in project:
            raise HTTPException(status_code=400, detail="Project not found")
        pname, pver = project.split("/", 1)
        projectversion = db.query(ProjectVersion).join(Project).filter(
            Project.is_mirror.is_(False),
            func.lower(Project.name) == pname.lower(),
            func.lower(ProjectVersion.name) == pver.lower(),
        ).first()
        if not projectversion:
            raise HTTPException(status_code=400, detail="Projectversion not found")

    if projectversion:
        builds = builds.join(ProjectVersion, isouter=True).filter(
            ProjectVersion.id == projectversion.id
        )

    if not projectversion or projectversion.projectversiontype != "snapshot":
        builds = builds.filter(Build.snapshotbuild_id.is_(None))

    if version:
        builds = builds.filter(Build.version.ilike(f"%{version}%"))
    if maintainer:
        builds = builds.filter(Maintainer.fullname.ilike(f"%{maintainer}%"))
    if commit:
        builds = builds.filter(Build.git_ref.ilike(f"%{commit}%"))
    if architecture:
        builds = builds.filter(Build.architecture.ilike(f"%{architecture}%"))
    if sourcerepository:
        builds = builds.filter(or_(
            Build.sourcename.ilike(f"%{sourcerepository}%"),
            Build.sourcerepository.has(SourceRepository.url.ilike(f"%/{sourcerepository}%.git")),
        ))
    if startstamp:
        builds = builds.filter(
            func.to_char(Build.startstamp, "YYYY-MM-DD HH24:MI:SS").contains(startstamp)
        )
    if buildstate and set(buildstate).issubset(set(BUILD_STATES)):
        builds = builds.filter(or_(*[Build.buildstate == s for s in buildstate]))

    if search or search_project or project:
        child_cte = builds.cte("childs")
        parentbuilds = db.query(Build).filter(Build.id == child_cte.c.parent_id)
        parent_cte = parentbuilds.cte("parents")
        grandparentbuilds = db.query(Build).filter(Build.id == parent_cte.c.parent_id)
        builds = builds.union(parentbuilds, grandparentbuilds)

    nb_builds = builds.count()

    parent = aliased(Build)
    builds = builds.outerjoin(parent, parent.id == Build.parent_id)
    builds = builds.order_by(
        func.coalesce(parent.parent_id, Build.parent_id, Build.id).desc(), Build.id
    )

    results = pagination.apply(builds).all()
    return {"total_result_count": nb_builds, "results": [b.data() for b in results]}


@router.get("/api/build/{build_id}")
def get_build_tree(build_id: int, db: Session = Depends(get_db)):
    query = text("""
WITH RECURSIVE descendants AS (
    SELECT build.id, build.parent_id, 0 AS depth FROM build WHERE build.id = :build_id
    UNION
    SELECT p.id, p.parent_id, d.depth+1 FROM build p INNER JOIN descendants d ON p.parent_id = d.id
)
SELECT * FROM descendants ORDER BY id;
""")
    rows = db.execute(query, {"build_id": build_id}).fetchall()

    parents: dict = {}
    toplevel = None
    for row in rows:
        bid, depth = row[0], row[2]
        build = db.query(Build).filter(Build.id == bid).first()
        if not build:
            continue
        bdata = build.data()
        parents[build.id] = bdata
        if build.parent_id and build.parent_id in parents:
            parents[build.parent_id].setdefault("childs", []).append(bdata)
        if depth == 0:
            toplevel = bid

    return parents[toplevel] if toplevel else {}


class TriggerBuildBody(BaseModel):
    repository: str
    git_ref: Optional[str] = None
    git_branch: Optional[str] = None
    targets: Optional[list] = None
    force_ci: Optional[bool] = False


@router.post("/api/build")
async def trigger_build(
    body: TriggerBuildBody,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    result = db.execute(text("SELECT value FROM metadata WHERE name = :k"), {"k": "maintenance_mode"})
    row = result.fetchone()
    if row and row[0] == "true":
        raise HTTPException(status_code=503, detail="Maintenance Mode")

    repo = db.query(SourceRepository).filter(SourceRepository.url == body.repository).first()
    if not repo:
        raise HTTPException(status_code=400, detail="Repo not found")

    build = Build(
        version=None, git_ref=body.git_ref, ci_branch=body.git_branch,
        is_ci=False, sourcename=repo.name, buildstate="new", buildtype="build",
        sourcerepository=repo, maintainer=None,
    )
    db.add(build)
    db.commit()
    await build.build_added()

    if not body.git_ref:
        args = {"buildlatest": [repo.id, build.id]}
    else:
        args = {"build": [build.id, repo.id, body.git_ref, body.git_branch, body.targets, body.force_ci]}
    await enqueue_task(args)
    return {"build_id": str(build.id)}
