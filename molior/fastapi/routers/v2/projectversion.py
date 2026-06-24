"""
/api2/project/{project_name}/{project_version}  (project version operations)
Replaces molior/api2/projectversion.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api2", tags=["projectversions"])


@router.get("/project/{project_name}/{project_version}")
def get_projectversion(project_name: str, project_version: str, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/project/{project_name}/{project_version}/export")
def export_projectversion(project_name: str, project_version: str, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/project/{project_id}/{projectversion_id}/dependencies")
def list_dependencies(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/dependencies")
def add_dependency(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/project/{project_id}/{projectversion_id}/dependency/{dependency_name}/{dependency_version}")
def remove_dependency(
    project_id: str,
    projectversion_id: str,
    dependency_name: str,
    dependency_version: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/copy")
def copy_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/lock")
def lock_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/unlock")
def unlock_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/overlay")
def overlay_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/snapshot")
def snapshot_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/project/{project_id}/{projectversion_id}")
def delete_projectversion(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/project/{project_id}/{projectversion_id}/dependents")
def list_dependents(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/project/{project_name}/{project_version}/aptsources")
def get_aptsources(project_name: str, project_version: str, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/project/{project_id}/{projectversion_id}/repositories")
def list_repositories(
    project_id: str,
    projectversion_id: str,
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/repositories")
def add_repository(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.get("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def get_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.put("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def update_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.delete("/project/{project_id}/{projectversion_id}/repository/{sourcerepository_id}")
def remove_repository(
    project_id: str,
    projectversion_id: str,
    sourcerepository_id: int,
    current_user: CurrentUser = Depends(require_role(["member", "owner"])),
    db: Session = Depends(get_db),
):
    raise NotImplementedError


@router.post("/project/{project_id}/{projectversion_id}/extbuild")
def extbuild(
    project_id: str,
    projectversion_id: str,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    raise NotImplementedError
