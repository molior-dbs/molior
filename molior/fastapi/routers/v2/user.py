"""
/api2/user/{username}
Replaces molior/api2/user.py
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated
from ...db import get_db
from ....model.user import User

router = APIRouter(prefix="/api2", tags=["users"])


@router.get("/user/{username}")
def get_user(
    username: str,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "username": user.username,
        "email": user.email,
        "id": user.id,
        "is_admin": user.is_admin,
    }
