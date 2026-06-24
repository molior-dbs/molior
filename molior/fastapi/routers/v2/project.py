"""
/api2/projectbase  (project and project-version level operations)
Replaces molior/api2/project.py
"""

import hashlib
import json
from secrets import token_hex
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams
from ....model.authtoken import Authtoken
from ....model.authtoken_project import Authtoken_Project
from ....model.metadata import MetaData
from ....model.project import Project
from ....model.projectversion import (
    ProjectVersion, find_basemirror_or_baseproject, DEPENDENCY_POLICIES,
)
from ....model.projectversiondependency import ProjectVersionDependency
from ....model.sourepprover import SouRepProVer
from ....model.sourcerepository import SourceRepository
from ....model.user import User
from ....model.userrole import UserRole, USER_ROLES
from ....molior.queues import enqueue_aptly
from ....tools import array2db, db2array, escape_for_like, is_name_valid, parse_int

router = APIRouter(prefix="/api2", tags=["projects"])


def _get_project(project_name: str, db: Session):
    return db.query(Project).filter_by(name=project_name).first()


def _default_retention(db: Session, key: str):
    row = db.query(MetaData).filter_by(name=key).first()
    return row.value if row else None


# ---------------------------------------------------------------------------
# Project info
# ---------------------------------------------------------------------------

@router.get("/projectbase/{project_name}")
def get_project(
    project_name: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    return {"id": project.id, "name": project.name, "description": project.description}


# ---------------------------------------------------------------------------
# Project versions list
# ---------------------------------------------------------------------------

@router.get("/projectbase/{project_name}/versions")
def list_project_versions(
    project_name: str,
    basemirror_id: Optional[int] = Query(default=None),
    isbasemirror: Optional[bool] = Query(default=False),
    q: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(ProjectVersion).join(Project).filter(
        Project.is_mirror.is_(False),
        ProjectVersion.is_deleted.is_(False),
    )
    query = query.filter(
        or_(
            func.lower(Project.name) == project_name.lower(),
            Project.id == parse_int(project_name),
        )
    )
    if q:
        query = query.filter(
            ProjectVersion.name.ilike("%{}%".format(escape_for_like(q)))
        )
    if basemirror_id:
        query = query.filter(ProjectVersion.basemirror_id == basemirror_id)
    elif isbasemirror:
        query = query.filter(
            Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready"
        )
    query = query.order_by(ProjectVersion.id.desc())
    total = query.count()
    results = pagination.apply(query).all()
    return {"total_result_count": total, "results": [pv.data() for pv in results]}


# ---------------------------------------------------------------------------
# Create project version
# ---------------------------------------------------------------------------

class CreateProjectVersionBody(BaseModel):
    name: str
    description: Optional[str] = None
    dependency_policy: str = "strict"
    cibuilds: Optional[bool] = False
    architectures: List[str]
    basemirror: Optional[str] = None
    baseproject: Optional[str] = None
    retention_successful_builds: Optional[int] = None
    retention_failed_builds: Optional[int] = None


@router.post("/projectbase/{project_id}/versions")
async def create_project_version(
    project_id: str,
    body: CreateProjectVersionBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    if body.dependency_policy not in DEPENDENCY_POLICIES:
        raise HTTPException(status_code=400, detail="Wrong dependency policy")
    if not is_name_valid(body.name):
        raise HTTPException(status_code=400, detail="Invalid project name")
    if body.basemirror and "/" not in body.basemirror:
        raise HTTPException(status_code=400, detail="No basemirror received (format: 'name/version')")
    if body.baseproject and "/" not in body.baseproject:
        raise HTTPException(status_code=400, detail="No baseproject received (format: 'name/version')")
    if not body.architectures:
        raise HTTPException(status_code=400, detail="No architecture received")

    retention_ok = body.retention_successful_builds
    retention_fail = body.retention_failed_builds
    if retention_ok is None:
        retention_ok = _default_retention(db, "retention_successful_builds")
    if retention_fail is None:
        retention_fail = _default_retention(db, "retention_failed_builds")

    project = db.query(Project).filter(
        func.lower(Project.name) == project_id.lower()
    ).first()
    if not project:
        project = db.query(Project).filter(Project.id == parse_int(project_id)).first()
    if not project:
        raise HTTPException(status_code=400, detail=f"Project '{project_id}' not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot add projectversion to a mirror")

    existing = db.query(ProjectVersion).join(Project).filter(
        func.lower(ProjectVersion.name) == body.name.lower(), Project.id == project.id
    ).first()
    if existing:
        suffix = ", and is marked as deleted" if existing.is_deleted else ""
        raise HTTPException(status_code=400,
                            detail=f"Projectversion '{body.name}' already exists{suffix}")

    err, pv, bm = find_basemirror_or_baseproject(db, body.basemirror, body.baseproject)
    if err:
        raise HTTPException(status_code=400, detail=err.text)

    for arch in body.architectures:
        if arch not in db2array(bm.mirror_architectures):
            raise HTTPException(status_code=400,
                                detail=f"Architecture not found in basemirror: {arch}")

    projectversion = ProjectVersion(
        name=body.name,
        project=project,
        description=body.description,
        dependency_policy=body.dependency_policy,
        ci_builds_enabled=body.cibuilds,
        mirror_architectures=array2db(body.architectures),
        basemirror=bm,
        mirror_state=None,
        retention_successful_builds=retention_ok,
        retention_failed_builds=retention_fail,
    )
    db.add(projectversion)
    db.commit()

    if body.baseproject:
        pdep = ProjectVersionDependency(
            projectversion_id=projectversion.id,
            dependency_id=pv.id,
            use_cibuilds=False,
        )
        db.add(pdep)
        db.commit()

    await enqueue_aptly({"init_repository": [
        bm.project.name, bm.name,
        projectversion.project.name, projectversion.name,
        body.architectures, [],
    ]})
    return {"id": projectversion.id, "name": projectversion.name}


# ---------------------------------------------------------------------------
# Edit project version
# ---------------------------------------------------------------------------

class EditProjectVersionBody(BaseModel):
    description: Optional[str] = None
    dependency_policy: Optional[str] = None
    cibuilds: Optional[bool] = None
    retention_successful_builds: Optional[int] = None
    retention_failed_builds: Optional[int] = None


@router.put("/project/{project_id}/{projectversion_id}")
def update_project_version(
    project_id: str,
    projectversion_id: str,
    body: EditProjectVersionBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    from ._helpers import resolve_projectversion
    if body.dependency_policy and body.dependency_policy not in DEPENDENCY_POLICIES:
        raise HTTPException(status_code=400, detail="Wrong dependency policy")

    projectversion = resolve_projectversion(project_id, projectversion_id, db)
    if not projectversion:
        raise HTTPException(status_code=400, detail="Projectversion not found")

    retention_ok = body.retention_successful_builds
    retention_fail = body.retention_failed_builds
    if retention_ok is None:
        retention_ok = _default_retention(db, "retention_successful_builds")
    if retention_fail is None:
        retention_fail = _default_retention(db, "retention_failed_builds")

    if body.dependency_policy:
        for dep in projectversion.dependents:
            if body.dependency_policy == "strict" and dep.basemirror_id != projectversion.basemirror_id:
                raise HTTPException(status_code=400,
                                    detail="Cannot change dependency policy: strict requires same basemirror")
            if body.dependency_policy == "distribution" and \
               dep.basemirror.project_id != projectversion.basemirror.project_id:
                raise HTTPException(status_code=400,
                                    detail="Cannot change dependency policy: distribution requires same distribution")
        projectversion.dependency_policy = body.dependency_policy

    projectversion.description = body.description
    if body.cibuilds is not None:
        projectversion.ci_builds_enabled = body.cibuilds
    projectversion.retention_successful_builds = retention_ok
    projectversion.retention_failed_builds = retention_fail
    db.commit()
    return {"id": projectversion.id, "name": projectversion.name}


# ---------------------------------------------------------------------------
# Delete project
# ---------------------------------------------------------------------------

@router.delete("/projectbase/{project_id}")
def delete_project(
    project_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(name=project_id).first()
    if not project:
        raise HTTPException(status_code=400, detail="Project not found")
    if project.projectversions:
        raise HTTPException(status_code=400,
                            detail="Cannot delete project containing projectversions")

    for ur in db.query(UserRole).join(User).join(Project).filter(Project.id == project.id).all():
        db.delete(ur)
    for t in db.query(Authtoken_Project).filter(Authtoken_Project.project_id == project.id).all():
        db.delete(t)
    db.delete(project)
    db.commit()
    return f"project {project_id} deleted"


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

@router.get("/projectbase/{project_name}/permissions")
def list_permissions(
    project_name: str,
    candidates: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot get permissions from a mirror")

    if candidates:
        query = db.query(User).outerjoin(UserRole).outerjoin(Project)
        query = query.filter(User.username != "admin")
        query = query.filter(
            or_(UserRole.project_id.is_(None), Project.id != project.id)
        )
        if q:
            query = query.filter(
                User.username.ilike("%{}%".format(escape_for_like(q)))
            )
        query = query.order_by(User.username)
        total = query.count()
        users = pagination.apply(query).all()
        return {
            "total_result_count": total,
            "results": [{"id": u.id, "username": u.username} for u in users],
        }

    query = db.query(UserRole).join(User).join(Project).order_by(User.username)
    query = query.filter(Project.id == project.id)
    if q:
        query = query.filter(
            User.username.ilike("%{}%".format(escape_for_like(q)))
        )
    if role:
        for r in USER_ROLES:
            if role.lower() in r:
                query = query.filter(UserRole.role == r)
    total = query.count()
    roles = pagination.apply(query).all()
    return {
        "total_result_count": total,
        "results": [{"id": r.user.id, "username": r.user.username, "role": r.role} for r in roles],
    }


class PermissionBody(BaseModel):
    username: str
    role: Optional[str] = None


@router.post("/projectbase/{project_name}/permissions")
def add_permission(
    project_name: str,
    body: PermissionBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    if body.role not in ["member", "manager", "owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    if body.username == "admin":
        raise HTTPException(status_code=400, detail="User not allowed")

    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot set permissions on a mirror")

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(UserRole).join(User).join(Project).filter(
        User.username == body.username, Project.id == project.id
    ).all()
    if existing:
        raise HTTPException(status_code=400, detail="User permission already added")

    db.add(UserRole(user_id=user.id, project_id=project.id, role=body.role))
    db.commit()
    return ""


@router.put("/projectbase/{project_name}/permissions")
def update_permission(
    project_name: str,
    body: PermissionBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    if body.role not in ["member", "manager", "owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    if body.username == "admin":
        raise HTTPException(status_code=400, detail="User not allowed")

    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot edit permissions on a mirror")

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    userrole = db.query(UserRole).filter(
        UserRole.project_id == project.id, UserRole.user_id == user.id
    ).first()
    if not userrole:
        raise HTTPException(status_code=400, detail="User Role not found")
    userrole.role = body.role
    db.commit()
    return ""


class DeletePermissionBody(BaseModel):
    username: str


@router.delete("/projectbase/{project_name}/permissions")
def remove_permission(
    project_name: str,
    body: DeletePermissionBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    if body.username == "admin":
        raise HTTPException(status_code=400, detail="User not allowed")

    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot delete permissions from a mirror")

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    userrole = db.query(UserRole).join(User).join(Project).filter(
        User.username == body.username, Project.id == project.id
    ).first()
    if userrole:
        db.delete(userrole)
        db.commit()
    return ""


# ---------------------------------------------------------------------------
# Project tokens
# ---------------------------------------------------------------------------

@router.get("/projectbase/{project_name}/tokens")
def list_project_tokens(
    project_name: str,
    description: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")

    query = db.query(Authtoken).outerjoin(Authtoken_Project).outerjoin(Project)
    query = query.filter(Project.id == project.id)
    if description:
        query = query.filter(
            Authtoken.description.ilike("%{}%".format(escape_for_like(description)))
        )
    total = query.count()
    tokens = pagination.apply(query).all()
    return {
        "total_result_count": total,
        "results": [{"id": t.id, "description": t.description} for t in tokens],
    }


class TokenBody(BaseModel):
    description: Optional[str] = None


@router.post("/projectbase/{project_name}/token")
def create_project_token(
    project_name: str,
    body: TokenBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot create auth token for mirrors")

    raw = token_hex(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    token = Authtoken(description=body.description, token=hashed)
    db.add(token)
    db.commit()
    mapping = Authtoken_Project(
        project_id=project.id, authtoken_id=token.id, roles=array2db(["owner"])
    )
    db.add(mapping)
    db.commit()
    return {"token": raw}


@router.put("/projectbase/{project_name}/token")
def associate_project_token(
    project_name: str,
    body: TokenBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot create auth token for mirrors")

    token = db.query(Authtoken).filter_by(description=body.description).first()
    if not token:
        raise HTTPException(status_code=404, detail=f"Authtoken '{body.description}' not found")

    mapping = Authtoken_Project(
        project_id=project.id, authtoken_id=token.id, roles=array2db(["owner"])
    )
    db.add(mapping)
    db.commit()
    return ""


class DeleteTokenBody(BaseModel):
    id: int


@router.delete("/projectbase/{project_name}/tokens")
def remove_project_token(
    project_name: str,
    body: DeleteTokenBody,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = _get_project(project_name, db)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found")

    token = db.query(Authtoken_Project).filter(
        Authtoken_Project.authtoken_id == body.id,
        Authtoken_Project.project_id == project.id,
    ).first()
    if not token:
        raise HTTPException(status_code=404, detail=f"Token not found in {project_name}")

    db.delete(token)
    db.commit()
    return ""


# ---------------------------------------------------------------------------
# Import project version
# ---------------------------------------------------------------------------

@router.post("/projectbase/projectversion/import")
async def import_projectversion(
    current_user: CurrentUser = Depends(require_role("owner")),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid file type.")

    content = await file.read()
    try:
        json_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Failed to parse JSON data.")

    name = json_data.get("name")
    project_id = json_data.get("project_name")
    description = json_data.get("description")
    architectures = json_data.get("architectures")
    basemirror = json_data.get("basemirror")
    cibuilds = json_data.get("ci_builds_enabled")
    dependency_policy = json_data.get("dependency_policy")
    retention_ok = json_data.get("retention_successful_builds")
    retention_fail = json_data.get("retention_failed_builds")
    sourcerepositories = json_data.get("sourcerepositories")
    baseproject = json_data.get("baseproject", "")

    if not is_name_valid(name):
        raise HTTPException(status_code=400, detail="Invalid project name")

    project = db.query(Project).filter(
        func.lower(Project.name) == project_id.lower()
    ).first()
    if not project:
        raise HTTPException(status_code=400, detail=f"Project '{project_id}' not found")
    if project.is_mirror:
        raise HTTPException(status_code=400, detail="Cannot add projectversion to a mirror")

    existing = db.query(ProjectVersion).join(Project).filter(
        func.lower(ProjectVersion.name) == name.lower(), Project.id == project.id
    ).first()
    if existing:
        suffix = ", and is marked as deleted" if existing.is_deleted else ""
        raise HTTPException(status_code=400,
                            detail=f"Projectversion '{name}' already exists{suffix}")

    bm = None
    pv = None
    if baseproject:
        bp_name, bp_version = baseproject.split("/")
        pv = db.query(ProjectVersion).join(Project).filter(
            Project.is_basemirror.is_(False),
            func.lower(Project.name) == bp_name.lower(),
            func.lower(ProjectVersion.name) == bp_version.lower(),
        ).first()
        if not pv:
            raise HTTPException(status_code=400,
                                detail=f"Base project not found: {baseproject}")
        bm = pv.basemirror
    else:
        bm_name, bm_version = basemirror.split("/")
        bm = db.query(ProjectVersion).join(Project).filter(
            Project.is_basemirror.is_(True),
            func.lower(Project.name) == bm_name.lower(),
            func.lower(ProjectVersion.name) == bm_version.lower(),
        ).first()
        if not bm:
            raise HTTPException(status_code=400,
                                detail=f"Base mirror not found: {basemirror}")

    for arch in architectures:
        if arch not in db2array(bm.mirror_architectures):
            raise HTTPException(status_code=400,
                                detail=f"Architecture not found in basemirror: {arch}")

    projectversion = ProjectVersion(
        name=name,
        project=project,
        description=description,
        dependency_policy=dependency_policy,
        ci_builds_enabled=cibuilds,
        mirror_architectures=array2db(architectures),
        basemirror=bm,
        mirror_state=None,
        retention_successful_builds=retention_ok,
        retention_failed_builds=retention_fail,
    )
    db.add(projectversion)
    db.flush()

    if baseproject and pv:
        db.add(ProjectVersionDependency(
            projectversion_id=projectversion.id,
            dependency_id=pv.id,
            use_cibuilds=False,
        ))

    for repo_data in (sourcerepositories or []):
        repo_url = repo_data.get("url")
        repo_archs = repo_data.get("architectures", architectures)
        repo_archs = [a for a in repo_archs if a in architectures]
        repo = db.query(SourceRepository).filter(SourceRepository.url == repo_url).first()
        if repo:
            if repo not in projectversion.sourcerepositories:
                projectversion.sourcerepositories.append(repo)
                db.flush()
            srpv = db.query(SouRepProVer).filter(
                SouRepProVer.sourcerepository_id == repo.id,
                SouRepProVer.projectversion_id == projectversion.id,
            ).first()
            if srpv:
                srpv.architectures = array2db(repo_archs)

    db.commit()

    await enqueue_aptly({"init_repository": [
        bm.project.name, bm.name,
        projectversion.project.name, projectversion.name,
        architectures, [],
    ]})

    return {"projectversion": projectversion.data(), "sourcerepositories": sourcerepositories}
