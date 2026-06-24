"""
/api/projects, /api/projects/{id}, /api/projectsources/{name}/{version}
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin, require_role
from ...db import get_db
from ...responses import PaginationParams
from ....logger import logger
from ....model.authtoken import Authtoken
from ....model.authtoken_project import Authtoken_Project
from ....model.build import Build
from ....model.project import Project
from ....model.projectversion import ProjectVersion, get_projectversion_deps
from ....model.user import User
from ....model.userrole import UserRole
from ....molior.configuration import Configuration
from ....tools import array2db, escape_for_like, is_name_valid

router = APIRouter(tags=["projects"])


@router.get("/api/projects")
def get_projects(
    q: Optional[str] = Query(default=""),
    pagination: PaginationParams = Depends(),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(Project).filter(Project.is_mirror.is_(False)).order_by(func.lower(Project.name))
    if q:
        query = query.filter(Project.name.ilike(f"%{escape_for_like(q)}%"))

    total = query.count()
    results = pagination.apply(query).all()

    data = []
    for project in results:
        build_count = db.query(Build).join(ProjectVersion).join(Project).filter(
            Project.id == project.id, Build.is_ci.is_(False)
        ).count()
        ci_count = db.query(Build).join(ProjectVersion).join(Project).filter(
            Project.id == project.id, Build.is_ci.is_(True)
        ).count()
        data.append({
            "id": project.id, "name": project.name, "description": project.description,
            "projectversionCount": len(project.projectversions),
            "buildCount": build_count, "cibuildCount": ci_count,
        })
    return {"total_result_count": total, "results": data}


@router.get("/api/projects/{project_id}")
def get_project(
    project_id: int,
    show_deleted: Optional[bool] = Query(default=False),
    _: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    versions = db.query(ProjectVersion).filter_by(
        project_id=project.id, is_deleted=show_deleted
    ).order_by(func.lower(ProjectVersion.name).desc()).all()

    return {
        "id": project.id, "name": project.name, "description": project.description,
        "versions": [{"id": v.id, "name": v.name, "is_locked": v.is_locked} for v in versions],
        "versions_map": {v.id: v.name for v in versions},
    }


class CreateProjectBody(BaseModel):
    name: str
    description: Optional[str] = None


@router.post("/api/projects")
def create_project(
    body: CreateProjectBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not body.name:
        raise HTTPException(status_code=400, detail="No project name given")
    if not is_name_valid(body.name):
        raise HTTPException(status_code=400, detail="Invalid project name")
    if db.query(Project).filter(func.lower(Project.name) == body.name.lower()).first():
        raise HTTPException(status_code=400, detail="Projectname is already taken")

    project = Project(name=body.name, description=body.description)
    db.add(project)
    db.commit()

    if current_user.username and current_user.username != "admin":
        user = db.query(User).filter(User.username == current_user.username).first()
        if user:
            db.add(UserRole(user_id=user.id, project_id=project.id, role="owner"))
            db.commit()
    elif current_user.auth_token:
        token = db.query(Authtoken).filter(Authtoken.token == current_user.auth_token).first()
        if token:
            db.add(Authtoken_Project(project_id=project.id, authtoken_id=token.id, roles=array2db(["owner"])))
            db.commit()
    return {}


class UpdateProjectBody(BaseModel):
    description: Optional[str] = None


@router.put("/api/projects/{project_id}")
@router.put("/api/projectbase/{project_id}")
def update_project(
    project_id: int,
    body: UpdateProjectBody,
    _: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    project.description = body.description
    db.commit()
    return "project updated"


@router.get("/api/projectsources/{project_name}/{project_version}",
            response_class=PlainTextResponse)
def get_apt_sources(
    project_name: str,
    project_version: str,
    unstable: Optional[str] = Query(default=""),
    db: Session = Depends(get_db),
):
    pv = db.query(ProjectVersion).join(Project).filter(
        func.lower(Project.name) == project_name.lower(),
        func.lower(ProjectVersion.name) == project_version.lower(),
    ).first()
    if not pv:
        raise HTTPException(status_code=400, detail="projectversion not found")

    deps = [(pv.id, pv.ci_builds_enabled)] + get_projectversion_deps(pv.id, db)

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public") or cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources = f"# APT Sources for project {pv.project.name} {pv.name}\n"
    sources += f"# GPG-Key: {apt_url}/{keyfile}\n"
    if not pv.project.is_basemirror and pv.basemirror:
        sources += "# Base Mirror\n"
        sources += f"{pv.basemirror.get_apt_repo()}\n"

    sources += "# Project Sources\n"
    for dep_id, use_ci in deps:
        dep = db.query(ProjectVersion).filter(ProjectVersion.id == dep_id).first()
        if not dep:
            logger.error("projectsources: projectversion %d not found", dep_id)
            continue
        sources += f"{dep.get_apt_repo()}\n"
        if unstable == "true" and use_ci and dep.ci_builds_enabled:
            sources += f"{dep.get_apt_repo(dist='unstable')}\n"

    return sources
