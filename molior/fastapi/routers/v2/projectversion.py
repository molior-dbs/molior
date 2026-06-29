"""
/api2/project/{project_name}/{project_version}  (project version operations)
Replaces molior/api2/projectversion.py
"""

import json
from typing import List, Optional

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, BackgroundTasks
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams
from ._helpers import resolve_projectversion
from ....logger import logger
from ....model.build import Build
from ....model.metadata import MetaData
from ....model.project import Project
from ....model.projectversion import (
    ProjectVersion, find_basemirror_or_baseproject,
    get_projectversion_byname, get_projectversion_deps,
)
from ....model.projectversiondependency import ProjectVersionDependency
from ....model.sourcerepository import SourceRepository
from ....model.sourepprover import SouRepProVer
from ....molior.configuration import Configuration
from ....aptly.api import get_aptly_connection
from ....molior.queues import buildlog, buildlogdone, buildlogtitle, enqueue_aptly
from ....tools import array2db, db2array, escape_for_like, is_name_valid

router = APIRouter(prefix="/api2", tags=["projectversions"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latest_project_builds(db, projectversion_id):
    """Return latest successful deb builds per source repo for a project version."""
    latest_builds_subq = db.query(
        func.max(Build.id).label("latest_id")
    ).filter(
        Build.projectversion_id == projectversion_id,
        Build.is_ci.is_(False),
        Build.sourcerepository_id.isnot(None),
        Build.buildtype == "deb",
        Build.buildstate == "successful",
    ).group_by(Build.sourcerepository_id)

    SourceBuild = aliased(Build)
    latest_upload_subq = db.query(
        func.max(Build.id).label("latest_id")
    ).join(SourceBuild, SourceBuild.id == Build.parent_id).filter(
        Build.projectversion_id == projectversion_id,
        Build.is_ci.is_(False),
        Build.sourcerepository_id.is_(None),
        Build.buildtype == "deb",
        Build.buildstate == "successful",
    ).group_by(SourceBuild.sourcename)

    union_subq = latest_builds_subq.union_all(latest_upload_subq).subquery()
    return (
        db.query(Build)
        .join(union_subq, Build.id == union_subq.c.latest_id)
        .order_by(Build.sourcename, Build.id.desc())
        .all()
    )


def _do_lock(projectversion_id: int, db: Session):
    pv = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    for dep_id, _ in get_projectversion_deps(pv.id, db):
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
        if dep and not dep.is_locked:
            raise HTTPException(status_code=400,
                                detail="Dependencies of given projectversion must be locked")
    pv.is_locked = True
    pv.ci_builds_enabled = False
    db.commit()
    logger.info("ProjectVersion '%s/%s' locked", pv.project.name, pv.name)
    return "Locked Project Version"


def _do_unlock(projectversion_id: int, db: Session):
    pv = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    pv.is_locked = False
    pv.ci_builds_enabled = False
    db.commit()
    logger.info("ProjectVersion '%s/%s' unlocked", pv.project.name, pv.name)
    return "Unlocked Project Version"


def _do_overlay(name: str, projectversion_id: int, db: Session):
    if not name:
        raise HTTPException(status_code=400,
                            detail="No valid name for the projectversion received")
    if not is_name_valid(name):
        raise HTTPException(status_code=400, detail="Invalid project name")

    pv = db.query(ProjectVersion).filter(ProjectVersion.id == projectversion_id).first()
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")

    existing = db.query(ProjectVersion).filter(
        func.lower(ProjectVersion.name) == name.lower(),
        ProjectVersion.project_id == pv.project_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Overlay already exists")

    overlay = ProjectVersion(
        name=name,
        project=pv.project,
        dependencies=[pv],
        mirror_architectures=pv.mirror_architectures,
        basemirror=pv.basemirror,
        description=pv.description,
        dependency_policy=pv.dependency_policy,
        ci_builds_enabled=pv.ci_builds_enabled,
        projectversiontype="overlay",
        baseprojectversion_id=pv.id,
    )
    db.add(overlay)
    db.commit()

    bm = overlay.basemirror
    await_enqueue = {"init_repository": [
        bm.project.name, bm.name,
        overlay.project.name, overlay.name,
        db2array(overlay.mirror_architectures), [],
    ]}
    return overlay, await_enqueue


# ---------------------------------------------------------------------------
# Get / Export
# ---------------------------------------------------------------------------

@router.get("/project/{project_name}/{project_version}")
def get_projectversion(
    project_name: str,
    project_version: str,
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_name, project_version, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.project.is_mirror:
        raise HTTPException(status_code=400, detail="Projectversion is mirror")
    return pv.data()


@router.get("/project/{project_name}/{project_version}/export")
def export_projectversion(
    project_name: str,
    project_version: str,
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_name, project_version, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.project.is_mirror:
        raise HTTPException(status_code=400, detail="Projectversion is mirror")

    query = db.query(ProjectVersion, SouRepProVer, SourceRepository).join(
        ProjectVersion, ProjectVersion.id == SouRepProVer.projectversion_id
    ).join(
        SourceRepository, SouRepProVer.sourcerepository_id == SourceRepository.id
    ).filter(ProjectVersion.name == pv.name).all()

    sourcerepositories_data = [
        {
            "id": sr.id,
            "name": sr.name,
            "url": sr.url,
            "run_lintian": srpv.run_lintian,
            "architectures": db2array(srpv.architectures),
        }
        for _pv, srpv, sr in query
    ]

    data_object = pv.data()
    data_object["sourcerepositories"] = sourcerepositories_data
    json_data = json.dumps(data_object, indent=4)

    filename = f"{pv.project.name}_{pv.name}.projectversion_export.json"
    return Response(
        content=json_data,
        media_type="application/json",
        headers={"Content-Disposition": f"Attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# APT Sources
# ---------------------------------------------------------------------------

@router.get("/project/{project_name}/{project_version}/aptsources",
            response_class=PlainTextResponse)
def get_aptsources(
    project_name: str,
    project_version: str,
    unstable: Optional[bool] = Query(default=False),
    internal: Optional[bool] = Query(default=False),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_name, project_version, db)
    if not pv:
        raise HTTPException(status_code=400, detail="projectversion not found")

    deps = [(pv.id, pv.ci_builds_enabled)] + get_projectversion_deps(pv.id, db)

    cfg = Configuration()
    apt_url = (None if internal else cfg.aptly.get("apt_url_public")) or cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources = f"# APT Sources for project {pv.project.name} {pv.name}\n"
    sources += f"# GPG-Key: {apt_url}/{keyfile}\n"
    if not pv.project.is_basemirror and pv.basemirror:
        sources += "\n# Base Mirror\n"
        sources += "{}\n".format(pv.basemirror.get_apt_repo(internal=internal))
    sources += "\n# Project Sources\n"
    for dep_id, use_ci in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
        if not dep:
            logger.error("projectsources: projectversion %d not found", dep_id)
            continue
        sources += "{}\n".format(dep.get_apt_repo(internal=internal))
        if unstable and use_ci and dep.ci_builds_enabled:
            sources += "{}\n".format(dep.get_apt_repo(dist="unstable", internal=internal))
    return sources


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

@router.get("/project/{project_id}/{projectversion_id}/dependencies")
def list_dependencies(
    project_id: str,
    projectversion_id: str,
    candidates: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")

    dep_ids = [d.id for d in pv.dependencies]

    if candidates:
        BaseMirror = aliased(ProjectVersion)
        cands = db.query(ProjectVersion).filter(
            ProjectVersion.basemirror_id == pv.basemirror_id,
            ProjectVersion.id != pv.id,
            ProjectVersion.id.notin_(dep_ids),
        )
        dist_q = db.query(ProjectVersion).join(
            BaseMirror, BaseMirror.id == ProjectVersion.basemirror_id
        ).filter(
            ProjectVersion.dependency_policy == "distribution",
            BaseMirror.project_id == pv.basemirror.project_id,
            BaseMirror.id != pv.basemirror_id,
            ProjectVersion.id.notin_(dep_ids),
        )
        any_q = db.query(ProjectVersion).filter(
            ProjectVersion.dependency_policy == "any",
            ProjectVersion.id != pv.id,
            ProjectVersion.id.notin_(dep_ids),
        )
        if q:
            cands = cands.filter(ProjectVersion.fullname.ilike(f"%{escape_for_like(q)}%"))
            dist_q = dist_q.filter(ProjectVersion.fullname.ilike(f"%{escape_for_like(q)}%"))
            any_q = any_q.filter(ProjectVersion.fullname.ilike(f"%{escape_for_like(q)}%"))
        results = [c.data() for c in cands.all()] + \
                  [c.data() for c in dist_q.all()] + \
                  [c.data() for c in any_q.all()]
        return {"total_result_count": len(results), "results": results}

    # existing dependencies, de-duplicated
    seen = set()
    results = []
    for d in pv.dependencies:
        if d.id in seen:
            continue
        seen.add(d.id)
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d.id)
        if q:
            dep = dep.filter(ProjectVersion.fullname.ilike(f"%{q}%"))
        dep = dep.first()
        if dep:
            results.append(dep.data())
    return {"total_result_count": len(results), "results": results}


class AddDependencyBody(BaseModel):
    dependency: str
    use_cibuilds: Optional[bool] = False


@router.post("/project/{project_id}/{projectversion_id}/dependencies")
def add_dependency(
    project_id: str,
    projectversion_id: str,
    body: AddDependencyBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot add dependencies to a mirror")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Cannot add dependencies on a locked projectversion")

    dependency = get_projectversion_byname(body.dependency, db)
    if not dependency:
        raise HTTPException(status_code=400, detail="Dependency not found")
    if dependency.id == pv.id:
        raise HTTPException(status_code=400, detail="Cannot add dependency on itself")
    if dependency.project.is_basemirror:
        raise HTTPException(status_code=400, detail="Cannot add a basemirror as dependency")

    if dependency.dependency_policy == "strict":
        if dependency.basemirror_id != pv.basemirror_id:
            raise HTTPException(status_code=400,
                                detail="Cannot add dependency with different basemirror (strict policy)")
    elif dependency.dependency_policy == "distribution":
        if dependency.basemirror.project.id != pv.basemirror.project.id:
            raise HTTPException(status_code=400,
                                detail="Cannot add dependency from different distribution (distribution policy)")

    deps = get_projectversion_deps(dependency.id, db)
    dep_ids = [d[0] for d in deps]
    if pv.id in dep_ids:
        raise HTTPException(status_code=400, detail="Circular dependency detected")
    if dependency.id in dep_ids:
        raise HTTPException(status_code=400, detail="Dependency already exists")

    use_ci = False if dependency.project.is_mirror else body.use_cibuilds
    db.add(ProjectVersionDependency(
        projectversion_id=pv.id, dependency_id=dependency.id, use_cibuilds=use_ci
    ))
    db.commit()
    return "Dependency added"


@router.delete("/project/{project_id}/{projectversion_id}/dependency"
               "/{dependency_name}/{dependency_version}")
def remove_dependency(
    project_id: str,
    projectversion_id: str,
    dependency_name: str,
    dependency_version: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot remove dependencies from a mirror")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    dependency = get_projectversion_byname(f"{dependency_name}/{dependency_version}", db)
    if not dependency or dependency not in pv.dependencies:
        raise HTTPException(status_code=400, detail="Dependency not found")

    pv.dependencies.remove(dependency)
    db.commit()
    return "Dependency deleted"


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------

class CopyBody(BaseModel):
    name: str
    description: Optional[str] = None
    dependency_policy: Optional[str] = None
    basemirror: Optional[str] = None
    baseproject: Optional[str] = None
    architectures: List[str]
    cibuilds: Optional[bool] = False
    buildlatest: Optional[bool] = False
    retention_successful_builds: Optional[int] = None
    retention_failed_builds: Optional[int] = None


@router.post("/project/{project_id}/{projectversion_id}/copy")
async def copy_projectversion(
    project_id: str,
    projectversion_id: str,
    body: CopyBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    if not is_name_valid(body.name):
        raise HTTPException(status_code=400, detail="Invalid project name!")
    if body.basemirror and "/" not in body.basemirror:
        raise HTTPException(status_code=400, detail="Invalid basemirror format (name/version)")
    if body.baseproject and "/" not in body.baseproject:
        raise HTTPException(status_code=400, detail="Invalid baseproject format (name/version)")
    if not body.architectures:
        raise HTTPException(status_code=400, detail="No architecture received")

    retention_ok = body.retention_successful_builds
    retention_fail = body.retention_failed_builds
    if retention_ok is None:
        row = db.query(MetaData).filter_by(name="retention_successful_builds").first()
        retention_ok = row.value if row else None
    if retention_fail is None:
        row = db.query(MetaData).filter_by(name="retention_failed_builds").first()
        retention_fail = row.value if row else None

    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=404, detail="Projectversion not found")

    existing = db.query(ProjectVersion).join(Project).filter(
        func.lower(ProjectVersion.name) == body.name.lower(),
        Project.id == pv.project_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Projectversion already exists.")

    err, bpv, bm = find_basemirror_or_baseproject(db, body.basemirror, body.baseproject)
    if err:
        raise HTTPException(status_code=400, detail=err.text)

    new_pv = pv.copy(db, body.name, body.description, body.dependency_policy,
                     bm.id, body.architectures, body.cibuilds, retention_ok, retention_fail)

    if body.baseproject:
        db.add(ProjectVersionDependency(
            projectversion_id=new_pv.id, dependency_id=bpv.id, use_cibuilds=False
        ))
        db.commit()

    trigger_builds = []
    if body.buildlatest:
        for latest_build in _latest_project_builds(db, pv.id):
            topbuild = latest_build.parent.parent
            if topbuild.sourcerepository is None:
                continue
            if topbuild.sourcerepository not in new_pv.sourcerepositories:
                continue
            build = Build(
                version=topbuild.version, git_ref=topbuild.git_ref,
                ci_branch=topbuild.ci_branch, is_ci=False, sourcename=topbuild.sourcename,
                buildstate="new", buildtype="build",
                sourcerepository=topbuild.sourcerepository, maintainer=None,
            )
            db.add(build)
            db.commit()
            await build.build_added()
            trigger_builds.append(build.id)

    copy_build = Build(
        version=body.name, git_ref=None, ci_branch=None, is_ci=False,
        sourcename=f"copy {pv.project.name}/{pv.name}",
        buildstate="new", buildtype="copy_projectversion",
        sourcerepository=None, maintainer=None,
    )
    db.add(copy_build)
    db.commit()
    await copy_build.build_added()
    await copy_build.set_building()
    db.commit()

    await enqueue_aptly({"init_repository": [
        bm.project.name, bm.name, pv.project.name, body.name,
        body.architectures, trigger_builds, copy_build.id,
    ]})
    return {"build_id": copy_build.id, "rebuild_ids": trigger_builds}


# ---------------------------------------------------------------------------
# Lock / Unlock / Overlay / Snapshot
# ---------------------------------------------------------------------------

@router.post("/project/{project_id}/{projectversion_id}/lock")
def lock_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.basemirror.external_repo:
        raise HTTPException(status_code=400,
                            detail="Projectversion is based on external mirror")
    return _do_lock(pv.id, db)


@router.post("/project/{project_id}/{projectversion_id}/unlock")
def unlock_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.basemirror.external_repo:
        raise HTTPException(status_code=400,
                            detail="Projectversion is based on external mirror")
    return _do_unlock(pv.id, db)


class NameBody(BaseModel):
    name: str


@router.post("/project/{project_id}/{projectversion_id}/overlay")
async def overlay_projectversion(
    project_id: str,
    projectversion_id: str,
    body: NameBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    overlay, enqueue_args = _do_overlay(body.name, pv.id, db)
    await enqueue_aptly(enqueue_args)
    return {"id": overlay.id, "name": overlay.name}


@router.post("/project/{project_id}/{projectversion_id}/snapshot")
async def snapshot_projectversion(
    project_id: str,
    projectversion_id: str,
    body: NameBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.basemirror.external_repo:
        raise HTTPException(status_code=400, detail="Projectversion is based on external mirror")
    if pv.projectversiontype == "snapshot":
        raise HTTPException(status_code=400, detail="Cannot snapshot snapshots")
    if not is_name_valid(body.name):
        raise HTTPException(status_code=400, detail="Invalid project name")

    if db.query(ProjectVersion).join(Project).filter(
        func.lower(ProjectVersion.name) == body.name.lower(),
        Project.id == pv.project_id,
    ).first():
        raise HTTPException(status_code=400,
                            detail=f"Projectversion '{body.name}' already exists")

    for dep in pv.dependencies:
        if not dep.is_locked:
            raise HTTPException(
                status_code=400,
                detail=f"Dependency '{dep.project.name}/{dep.name}' is not locked",
            )

    latest_debbuilds_ids = []
    for latest_build in _latest_project_builds(db, pv.id):
        for debbuild in latest_build.parent.children:
            if debbuild.projectversion_id != pv.id:
                continue
            if not debbuild.debianpackages:
                raise HTTPException(
                    status_code=400,
                    detail=f"No debian packages found for {debbuild.sourcename}/{debbuild.version}",
                )
            latest_debbuilds_ids.append(debbuild.id)

    if not latest_debbuilds_ids:
        raise HTTPException(status_code=400, detail="No snapshotable builds found")

    new_pv = ProjectVersion(
        name=body.name,
        project=pv.project,
        dependencies=pv.dependencies,
        mirror_architectures=pv.mirror_architectures,
        basemirror_id=pv.basemirror_id,
        sourcerepositories=pv.sourcerepositories,
        ci_builds_enabled=False,
        is_locked=True,
        projectversiontype="snapshot",
        baseprojectversion_id=pv.id,
        dependency_policy=pv.dependency_policy,
    )
    db.add(new_pv)
    db.flush()

    for repo in new_pv.sourcerepositories:
        old_srpv = db.query(SouRepProVer).filter(
            SouRepProVer.sourcerepository_id == repo.id,
            SouRepProVer.projectversion_id == pv.id,
        ).first()
        new_srpv = db.query(SouRepProVer).filter(
            SouRepProVer.sourcerepository_id == repo.id,
            SouRepProVer.projectversion_id == new_pv.id,
        ).first()
        if old_srpv and new_srpv:
            new_srpv.architectures = old_srpv.architectures

    db.commit()

    await enqueue_aptly({"snapshot_repository": [
        pv.basemirror.project.name, pv.basemirror.name,
        pv.project.name, pv.name,
        db2array(pv.mirror_architectures),
        new_pv.name, new_pv.id, latest_debbuilds_ids,
    ]})
    return {"id": new_pv.id, "name": new_pv.name}


# ---------------------------------------------------------------------------
# Delete project version
# ---------------------------------------------------------------------------

@router.delete("/project/{project_id}/{projectversion_id}")
async def delete_projectversion(
    project_id: str,
    projectversion_id: str,
    forceremoval: Optional[bool] = Query(default=False),
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    blocking = [
        f"{d.project.name}/{d.name}"
        for d in pv.dependents
        if not d.is_deleted
    ]
    if blocking:
        raise HTTPException(
            status_code=400,
            detail="Projectversions '{}' are still depending on this version".format(
                ", ".join(blocking)
            ),
        )

    if not forceremoval:
        active = db.query(Build).filter(
            Build.projectversion_id == pv.id,
            Build.buildtype == "deb",
            or_(
                Build.buildstate == "needs_build",
                Build.buildstate == "scheduled",
                Build.buildstate == "building",
                Build.buildstate == "needs_publish",
                Build.buildstate == "publishing",
            ),
        ).first()
        if active:
            raise HTTPException(status_code=400,
                                detail="Builds are still running, cannot delete")

    pv.is_deleted = True
    pv.is_locked = True
    pv.ci_builds_enabled = False

    delete_build = Build(
        version=pv.name, git_ref=None, ci_branch=None, is_ci=False,
        sourcename=f"delete {pv.project.name}/{pv.name}",
        buildstate="new", buildtype="delete_projectversion",
        sourcerepository=None, maintainer=None,
    )
    db.add(delete_build)
    await delete_build.build_added()
    await delete_build.set_building()
    db.commit()

    await enqueue_aptly({"delete_repository": [pv.id, delete_build.id]})
    return {"build_id": delete_build.id}


# ---------------------------------------------------------------------------
# Dependents
# ---------------------------------------------------------------------------

@router.get("/project/{project_id}/{projectversion_id}/dependents")
def list_dependents(
    project_id: str,
    projectversion_id: str,
    candidates: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")

    dep_ids = [d.id for d in pv.dependents]

    if candidates:
        BaseMirror = aliased(ProjectVersion)
        cands = db.query(ProjectVersion).filter(
            ProjectVersion.basemirror_id == pv.basemirror_id,
            ProjectVersion.id != pv.id,
            ProjectVersion.id.notin_(dep_ids),
        )
        dist_q = db.query(ProjectVersion).join(
            BaseMirror, BaseMirror.id == ProjectVersion.basemirror_id
        ).filter(
            ProjectVersion.dependency_policy == "distribution",
            BaseMirror.project_id == pv.basemirror.project_id,
            BaseMirror.id != pv.basemirror_id,
            ProjectVersion.id.notin_(dep_ids),
        )
        any_q = db.query(ProjectVersion).filter(
            ProjectVersion.dependency_policy == "any",
            ProjectVersion.id != pv.id,
            ProjectVersion.id.notin_(dep_ids),
        )
        union = cands.union(dist_q, any_q).join(Project).order_by(
            Project.is_mirror, func.lower(Project.name), func.lower(ProjectVersion.name)
        )
        if q:
            union = union.filter(ProjectVersion.fullname.ilike(f"%{q}%"))
        results = [c.data() for c in union.all()]
        return {"total_result_count": len(results), "results": results}

    results = []
    for d in pv.dependents:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == d.id)
        if q:
            dep = dep.filter(ProjectVersion.fullname.ilike(f"%{q}%"))
        dep = dep.first()
        if dep:
            results.append(dep.data())
    return {"total_result_count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Repositories (list, add, get, edit, remove)
# ---------------------------------------------------------------------------

@router.get("/project/{project_id}/{projectversion_id}/repositories")
def list_repositories(
    project_id: str,
    projectversion_id: str,
    filter_url: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")

    query = db.query(SourceRepository, SouRepProVer).filter(
        SouRepProVer.sourcerepository_id == SourceRepository.id,
        SouRepProVer.projectversion_id == pv.id,
    ).filter(SourceRepository.projectversions.any(id=pv.id))

    if filter_url:
        query = query.filter(SourceRepository.url.ilike(f"%{filter_url}%"))

    count = query.count()
    query = query.order_by(SourceRepository.name)
    results_raw = pagination.apply(query).all()

    def _last_gitref(repo):
        b = db.query(Build).filter(
            Build.sourcerepository_id == repo.id,
            Build.buildtype == "source",
        ).order_by(Build.id.desc()).first()
        return b.git_ref if b else None

    def _last_build(repo):
        return db.query(Build).filter(
            Build.sourcerepository_id == repo.id,
            Build.projectversion_id == pv.id,
            Build.buildtype == "deb",
        ).order_by(Build.id.desc()).first()

    def _last_successful_build(repo):
        return db.query(Build).filter(
            Build.sourcerepository_id == repo.id,
            Build.projectversion_id == pv.id,
            Build.buildtype == "deb",
            Build.buildstate == "successful",
        ).order_by(Build.id.desc()).first()

    results = []
    for repo, srpv in results_raw:
        entry = {
            "id": repo.id,
            "name": repo.name,
            "url": repo.url,
            "state": repo.state,
            "last_gitref": _last_gitref(repo),
            "architectures": db2array(srpv.architectures),
            "run_lintian": srpv.run_lintian,
        }
        build = _last_build(repo)
        if build:
            entry["last_build"] = {
                "id": build.id, "version": build.version,
                "buildstate": build.buildstate, "sourcename": build.sourcename,
            }
            if build.buildstate != "successful":
                suc = _last_successful_build(repo)
                if suc:
                    entry["last_successful_build"] = {
                        "id": suc.id, "version": suc.version,
                        "buildstate": suc.buildstate, "sourcename": suc.sourcename,
                    }
        results.append(entry)

    return {"total_result_count": count, "results": results}


class AddRepositoryBody(BaseModel):
    url: str
    architectures: List[str]
    startbuild: Optional[bool] = True
    run_lintian: Optional[bool] = False


@router.post("/project/{project_id}/{projectversion_id}/repositories")
async def add_repository(
    project_id: str,
    projectversion_id: str,
    body: AddRepositoryBody,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    import giturlparse
    from ....molior.queues import enqueue_task

    if not body.url:
        raise HTTPException(status_code=400, detail="No URL received")
    if not body.architectures:
        raise HTTPException(status_code=400, detail="No architectures received")

    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    try:
        repoinfo = giturlparse.parse(body.url)
    except giturlparse.parser.ParserError:
        raise HTTPException(status_code=400, detail="Invalid git URL")

    for arch in body.architectures:
        if arch not in db2array(pv.mirror_architectures):
            raise HTTPException(status_code=400, detail=f"Invalid architecture: {arch}")

    repo = db.query(SourceRepository).filter(SourceRepository.url == body.url).first()
    if not repo:
        q = db.query(SourceRepository).filter(or_(
            SourceRepository.url.ilike(
                f"%{repoinfo.resource}%{repoinfo.owner}%/{repoinfo.name}"
            ),
            SourceRepository.url.ilike(
                f"%{repoinfo.resource}%{repoinfo.owner}%/{repoinfo.name}.git"
            ),
        ))
        if q.count() >= 1:
            repo = q.first()
            logger.info("found similar repo %s", repo.url)
        else:
            repo = SourceRepository(url=body.url, name=repoinfo.name.lower(), state="new")
            db.add(repo)

    already_attached = repo in pv.sourcerepositories
    if not already_attached:
        pv.sourcerepositories.append(repo)
        db.commit()

    srpv = db.query(SouRepProVer).filter(
        SouRepProVer.sourcerepository_id == repo.id,
        SouRepProVer.projectversion_id == pv.id,
    ).first()
    if not already_attached:
        srpv.architectures = array2db(body.architectures)
    srpv.run_lintian = body.run_lintian
    db.commit()

    if repo.state == "new":
        build = Build(
            version=None, git_ref=None, ci_branch=None, is_ci=None,
            sourcename=repo.name, buildstate="new", buildtype="build",
            sourcerepository=repo, maintainer=None,
        )
        db.add(build)
        db.commit()
        await build.build_added()
        await enqueue_task({"clone": [build.id, repo.id]})
    elif body.startbuild:
        build = Build(
            version=None, git_ref=None, ci_branch=None, is_ci=None,
            sourcename=repo.name, buildstate="new", buildtype="build",
            sourcerepository=repo, maintainer=None,
        )
        db.add(build)
        db.commit()
        await build.build_added()
        await enqueue_task({"buildlatest": [repo.id, build.id]})

    return "SourceRepository added"


@router.get("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def get_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=404, detail="Project not found")

    srpv = db.query(SouRepProVer).filter(
        SouRepProVer.sourcerepository_id == sourcerepository_id,
        SouRepProVer.projectversion_id == pv.id,
    ).first()
    if not srpv:
        raise HTTPException(status_code=404, detail="SourceRepository not found in project")

    repo = db.query(SourceRepository).filter(
        SourceRepository.id == sourcerepository_id
    ).first()
    return {
        "id": repo.id, "name": repo.name, "url": repo.url, "state": repo.state,
        "architectures": db2array(srpv.architectures),
        "run_lintian": srpv.run_lintian,
    }


class EditRepositoryBody(BaseModel):
    architectures: List[str]
    run_lintian: Optional[bool] = False


@router.put("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def update_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    body: EditRepositoryBody,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    if not body.architectures:
        raise HTTPException(status_code=400, detail="No architectures received")

    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=404, detail="Project not found")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    for arch in body.architectures:
        if arch not in db2array(pv.mirror_architectures):
            raise HTTPException(status_code=400,
                                detail=f"Architecture not supported in this projectversion: {arch}")

    srpv = db.query(SouRepProVer).filter(
        SouRepProVer.sourcerepository_id == sourcerepository_id,
        SouRepProVer.projectversion_id == pv.id,
    ).first()
    if not srpv:
        raise HTTPException(status_code=404, detail="SourceRepository not found in project")

    srpv.architectures = array2db(body.architectures)
    srpv.run_lintian = body.run_lintian
    db.commit()
    return "SourceRepository changed"


@router.delete("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def remove_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    repo = db.query(SourceRepository).filter(
        SourceRepository.id == sourcerepository_id
    ).first()
    if not repo:
        raise HTTPException(status_code=400,
                            detail=f"Sourcerepository {sourcerepository_id} not found")

    srpv = db.query(SouRepProVer).filter(
        SouRepProVer.sourcerepository_id == sourcerepository_id,
        SouRepProVer.projectversion_id == pv.id,
    ).first()
    if not srpv:
        raise HTTPException(status_code=400,
                            detail="Could not find the sourcerepository for the projectversion")

    pv.sourcerepositories.remove(repo)
    db.commit()
    return "Sourcerepository removed from projectversion"


# ---------------------------------------------------------------------------
# S3 publish
# ---------------------------------------------------------------------------


class S3Body(BaseModel):
    publish_s3: bool = False
    s3_endpoint: Optional[str] = None
    s3_path: Optional[str] = None


@router.post("/project/{project_id}/{projectversion_id}/s3", status_code=201)
async def publish_s3(
    project_id: str,
    projectversion_id: str,
    body: S3Body,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Configure publishing to S3 for a project version."""
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    maintenance = db.query(MetaData).filter_by(name="maintenance_mode").first()
    if maintenance and maintenance.value == "true":
        raise HTTPException(status_code=503, detail="Maintenance mode")

    old_publish = pv.publish_s3
    old_endpoint = pv.s3_endpoint
    old_path = pv.s3_path

    pv.publish_s3 = body.publish_s3
    pv.s3_endpoint = body.s3_endpoint
    pv.s3_path = body.s3_path
    db.commit()

    if body.publish_s3 and not old_publish:
        await enqueue_aptly({"publish_s3": [pv.id]})
    elif not body.publish_s3 and old_publish:
        await enqueue_aptly({"remove_s3": [pv.id, old_endpoint, old_path]})
    elif body.publish_s3 and old_publish:
        if old_endpoint != body.s3_endpoint or old_path != body.s3_path:
            await enqueue_aptly({"remove_s3": [pv.id, old_endpoint, old_path]})
            await enqueue_aptly({"publish_s3": [pv.id]})

    return {"ok": True}


@router.get("/s3")
async def s3_endpoints(
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """List configured S3 endpoints from Aptly."""
    aptly = get_aptly_connection()
    data = await aptly.s3_endpoints()
    return data


# ---------------------------------------------------------------------------
# External build upload
# ---------------------------------------------------------------------------


async def _finalize_extbuild(build_id, projectversion_id, srcbuild_id, files):
    """Process uploaded external build files and trigger publishing."""
    cfg = Configuration()
    buildout_path = Path(cfg.working_dir) / "buildout"
    build_version = None
    sourcename = None
    source_pkg = None
    dsc_file = None
    source_upload = False
    has_changes_file = False
    has_buildinfo_file = False
    changes_file = None
    logs = []

    async def get_debbuild(arch, version, srcbuild_id, projectversion_id):
        if arch == "all":
            arch = "amd64"
        with Session() as db:
            debbuild = db.query(Build).filter(
                Build.version == version,
                Build.buildstate == "new",
                Build.buildtype == "deb",
                Build.parent_id == srcbuild_id,
                Build.projectversion_id == projectversion_id,
                Build.architecture == arch,
            ).first()
            if not debbuild:
                debbuild = Build(
                    version=version, git_ref=None, ci_branch=None, is_ci=False,
                    sourcename="external build upload", buildstate="new",
                    buildtype="deb", parent_id=srcbuild_id,
                    sourcerepository=None, maintainer=None,
                    projectversion_id=projectversion_id, architecture=arch,
                )
                db.add(debbuild)
                db.commit()
                await debbuild.build_added()
            return debbuild.id

    with Session() as db:
        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            await buildlog(build_id, "E: build not found: '%d'\n" % build_id)
            return False
        await build.log("I: Receiving uploaded files\n")

    for filename, tmp_path in files:
        # sanitise
        for ch in ("/", "$", "`", "'", '"', "\\"):
            filename = filename.replace(ch, "")

        await buildlog(build_id, " - %s\n" % filename)

        destbuild_id = None
        arch = pkgname = version = None

        if filename.endswith(".deb"):
            s = filename[:-4].split("_", 3)
            if len(s) != 3:
                logs.append("W: invalid filename: '%s'\n" % filename)
                continue
            pkgname, version, arch = s
            destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)

        elif filename.endswith(".changes"):
            s = filename[:-8].split("_", 3)
            if len(s) != 3:
                logs.append("W: invalid filename: '%s'\n" % filename)
                continue
            pkgname, version, arch = s
            arch = arch.split(".")[0]
            has_changes_file = True
            if not sourcename:
                sourcename = pkgname
            destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)
            changes_file = buildout_path / str(destbuild_id) / filename

        elif filename.endswith(".buildinfo"):
            s = filename[:-10].split("_", 3)
            if len(s) != 3:
                logs.append("W: invalid filename: '%s'\n" % filename)
                continue
            pkgname, version, arch = s
            arch = arch.split(".")[0]
            has_buildinfo_file = True
            if not sourcename:
                sourcename = pkgname
            destbuild_id = await get_debbuild(arch, version, srcbuild_id, projectversion_id)

        elif filename.endswith(".dsc"):
            s = filename[:-4].split("_", 2)
            if len(s) != 2:
                logs.append("W: invalid filename: '%s'\n" % filename)
                continue
            dsc_file = filename
            pkgname, version = s
            destbuild_id = srcbuild_id
            if not sourcename:
                sourcename = pkgname

        elif filename.endswith(".tar.gz") or filename.endswith(".tar.xz"):
            if source_upload:
                logs.append("W: only one source package allowed: '%s'\n" % filename)
                continue
            source_pkg = filename
            ext_len = 7 if filename.endswith(".tar.gz") else 7  # .tar.xz is also 7
            s = filename[:-ext_len].split("_", 2)
            if len(s) == 2:
                pkgname, version = s
                destbuild_id = srcbuild_id
                source_upload = True
                if not sourcename:
                    sourcename = pkgname
        else:
            logs.append("W: ignoring unknown file type: '%s'\n" % filename)
            continue

        if not build_version:
            build_version = version
        elif version != build_version:
            logs.append("E: version mismatch in uploaded files: '%s'\n" % version)
            shutil.rmtree(str(buildout_path / str(build_id)), ignore_errors=True)
            return False

        # move temp file to destination
        if destbuild_id is not None:
            dest_dir = buildout_path / str(destbuild_id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_path), str(dest_dir / filename))
        else:
            Path(tmp_path).unlink(missing_ok=True)

    with Session() as db:
        build = db.query(Build).filter(Build.id == build_id).first()
        srcbuild = db.query(Build).filter(Build.id == srcbuild_id).first()
        debbuilds = db.query(Build).filter(Build.parent_id == srcbuild_id).all()

        for log in logs:
            await buildlog(build_id, log)

        await buildlog(build_id, "I: Verifying uploaded files...\n")

        if not has_changes_file:
            await buildlog(build_id, "E: Missing *.changes file\n")
            await build.set_failed()
            await srcbuild.set_failed()
            for deb in debbuilds:
                await deb.set_failed()
            db.commit()
            return False

        if not has_buildinfo_file:
            await buildlog(build_id, "E: Missing *.buildinfo file\n")
            await build.set_failed()
            await srcbuild.set_failed()
            for deb in debbuilds:
                await deb.set_failed()
            db.commit()
            return False

        await buildlog(build_id, "I: Found external build: %s/%s\n" % (sourcename, build_version))

        if source_upload and dsc_file and changes_file:
            from launchy import Launchy

            async def outh(line):
                if line.strip():
                    logger.info(line)

            d = dsc_file.replace(".", "\\.")
            s = source_pkg.replace(".", "\\.")
            cmd = "sed -i -e '/%s$/d' -e '/%s$/d' %s" % (d, s, changes_file)
            process = Launchy(cmd, outh, outh)
            await process.launch()
            await process.wait()

        build.sourcename = sourcename
        srcbuild.sourcename = sourcename
        for deb in debbuilds:
            deb.sourcename = sourcename
        build.version = build_version
        srcbuild.version = build_version
        db.commit()

        existing = db.query(Build).filter(
            Build.buildtype == "build",
            Build.sourcerepository_id.is_(None),
            Build.projectversion_id == projectversion_id,
            Build.buildstate == "successful",
            Build.is_deleted.is_(False),
            Build.sourcename == sourcename,
            Build.version == build_version,
        ).first()
        if existing:
            await buildlog(build_id, "E: build for %s/%s already exists\n" % (sourcename, build_version))
            await build.set_failed()
            await buildlogtitle(build_id, "Done", no_footer_newline=True, no_header_newline=False)
            await srcbuild.set_failed()
            for deb in debbuilds:
                await deb.set_failed()
            db.commit()
            return False

        await build.set_building()
        db.commit()

        await srcbuild.logtitle("External Source Upload")
        if source_upload:
            await srcbuild.set_needs_publish()
            db.commit()
            await srcbuild.log("I: verifying source package\n")
            await enqueue_aptly({"src_publish": [srcbuild.id]})
        else:
            await srcbuild.log("W: no source package to publish\n")
            await srcbuild.set_nothing_done()
            db.commit()
            await buildlogtitle(srcbuild.id, "Done", no_footer_newline=True, no_header_newline=True)
            await buildlogdone(srcbuild.id)

        for deb in debbuilds:
            await deb.logtitle("External Debian Package Upload")
            await deb.set_needs_publish()
            db.commit()
            await deb.log("I: verifying debian packages\n")
            await enqueue_aptly({"publish": [deb.id]})

    return True


@router.post("/project/{project_id}/{projectversion_id}/extbuild", status_code=201)
async def extbuild(
    project_id: str,
    projectversion_id: str,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Accept external build artefacts (.deb, .changes, .buildinfo, .dsc, .tar.gz/.xz)."""
    pv = resolve_projectversion(project_id, projectversion_id, db)
    if not pv:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if pv.project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot upload to a mirror")
    if pv.is_locked:
        raise HTTPException(status_code=400, detail="Projectversion is locked")

    maintenance = db.query(MetaData).filter_by(name="maintenance_mode").first()
    if maintenance and maintenance.value == "true":
        raise HTTPException(status_code=503, detail="Maintenance mode")

    build = Build(
        version=None, git_ref=None, ci_branch=None, is_ci=False,
        sourcename="external build upload", buildstate="new", buildtype="build",
        sourcerepository=None, maintainer=None, projectversion_id=pv.id,
    )
    db.add(build)
    db.commit()
    await build.logtitle("External Build Upload")
    await build.build_added()

    srcbuild = Build(
        version="unknown", git_ref=None, ci_branch=None, is_ci=False,
        sourcename="external build upload", buildstate="new", buildtype="source",
        parent_id=build.id, sourcerepository=None, maintainer=None,
        projectversion_id=pv.id, projectversions=array2db([str(pv.id)]),
    )
    db.add(srcbuild)
    db.commit()
    await srcbuild.build_added()

    # Buffer uploaded files to temp paths so we can close the request
    cfg = Configuration()
    upload_dir = Path(cfg.working_dir) / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    buffered = []
    try:
        for f in files:
            with tempfile.NamedTemporaryFile(dir=upload_dir, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                while True:
                    chunk = await f.read(1 << 20)
                    if not chunk:
                        break
                    tmp.write(chunk)
            buffered.append((f.filename, tmp_path))
    except Exception as exc:
        logger.exception(exc)
        raise HTTPException(status_code=500, detail="Upload failed")

    background_tasks.add_task(
        asyncio.ensure_future,
        _finalize_extbuild(build.id, pv.id, srcbuild.id, buffered),
    )

    return {"build_id": build.id}
