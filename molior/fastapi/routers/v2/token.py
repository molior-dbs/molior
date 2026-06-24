"""
/api2/tokens
Replaces molior/api2/token.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db

router = APIRouter(prefix="/api2", tags=["tokens"])


@router.get("/tokens")
def list_tokens(current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.post("/tokens")
def create_token(current_user: CurrentUser = Depends(require_role("owner")), db: Session = Depends(get_db)):
    raise NotImplementedError


@router.delete("/tokens")
def delete_token(current_user: CurrentUser = Depends(require_role("owner")), db: Session = Depends(get_db)):
    raise NotImplementedError
