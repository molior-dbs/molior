"""
/api2/user/{username}
Replaces molior/api2/user.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated
from ...db import get_db

router = APIRouter(prefix="/api2", tags=["users"])


@router.get("/user/{username}")
def get_user(username: str, current_user: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)):
    raise NotImplementedError
