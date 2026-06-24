"""
/api/projects, /api/projectsources
Replaces molior/api/project.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin, require_role
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
def list_projects(
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/projects/{project_id}")
def get_project(project_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/projects")
def create_project(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/projects/{project_id}")
@router.put("/projectbase/{project_id}")
def update_project(project_id: str, current_user: CurrentUser = Depends(require_role("owner")), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/projectsources/{project_name}/{project_version}")
def project_sources(project_name: str, project_version: str, db: Session = Depends(get_db)):
    raise NotImplementedError
