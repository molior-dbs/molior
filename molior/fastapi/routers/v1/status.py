"""
/api/status, /api/nodes, /api/node/{machineID}
Replaces molior/api/status.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, require_admin
from ...db import get_db
from ...responses import PaginationParams

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/status/maintenance")
def set_maintenance(current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/nodes")
def list_nodes(pagination: PaginationParams = Depends(), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/node/{machine_id}")
def get_node(machine_id: str, db: Session = Depends(get_db)):
    raise NotImplementedError
