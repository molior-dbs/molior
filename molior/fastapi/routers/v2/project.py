"""
/api2/projectbase, /api2/project  (project-level operations)
Replaces molior/api2/project.py
"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api2", tags=["projects"])


@router.get("/projectbase/{project_name}")
def get_project(
    project_name: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/projectbase/{project_name}/versions")
def list_project_versions(
    project_name: str,
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/projectbase/{project_id}/versions")
def create_project_version(
    project_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/project/{project_id}/{projectversion_id}")
def update_project_version(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/projectbase/{project_id}")
def delete_project(
    project_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


# --- Permissions ---

@router.get("/projectbase/{project_name}/permissions")
def list_permissions(
    project_name: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/projectbase/{project_name}/permissions")
def add_permission(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/projectbase/{project_name}/permissions")
def update_permission(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/projectbase/{project_name}/permissions")
def remove_permission(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


# --- Tokens ---

@router.get("/projectbase/{project_name}/tokens")
def list_project_tokens(
    project_name: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/projectbase/{project_name}/token")
def create_project_token(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/projectbase/{project_name}/token")
def associate_project_token(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/projectbase/{project_name}/tokens")
def remove_project_token(
    project_name: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


# --- Import ---

@router.post("/projectbase/projectversion/import")
def import_projectversion(
    current_user: CurrentUser = Depends(require_role("owner")),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # TODO: port from molior/api2/project.py import_projectversion
    raise NotImplementedError
