"""
/api/builds, /api/build/{build_id}
/api2/build/{build_id} GET + PUT  (registered here per original — see API-Analysis observation #4)
Replaces molior/api/build.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, check_maintenance
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(tags=["builds"])


@router.get("/api/builds")
def list_builds(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    # TODO: port filtering logic from molior/api/build.py
    raise NotImplementedError


@router.get("/api/build/{build_id}")
def get_build(build_id: int, db: Session = Depends(get_db)):
    # TODO: port recursive CTE build tree query
    raise NotImplementedError


@router.post("/api/build")
def trigger_build(
    current_user: CurrentUser = Depends(authenticated),
    _maintenance: None = Depends(check_maintenance),
    db: Session = Depends(get_db),
):
    # TODO: port from molior/api/build.py
    raise NotImplementedError


# --- /api2/ build endpoints (kept here per original file layout) ---

@router.get("/api2/build/{build_id}")
def get_build_v2(build_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.put("/api2/build/{build_id}")
def rebuild_build(build_id: int, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError
