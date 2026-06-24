"""
/api/login, /api/logout, /api/userinfo
Replaces molior/api/auth.py
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, create_session_cookie
from ....auth.auth import Auth
from ...db import get_db
from ....model.user import User
from ....molior.configuration import Configuration

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login", status_code=200)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate and set a signed session cookie."""
    cfg = Configuration()

    # Built-in admin
    if body.username == "admin":
        if body.password != cfg.admin.get("admin_password", ""):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    else:
        if not Auth().login(body.username, body.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Ensure user exists in DB (create on first login)
        user = db.query(User).filter_by(username=body.username).first()
        if not user:
            user = User(username=body.username)
            if db.query(User).count() < 1:
                user.is_admin = True
            db.add(user)
            db.commit()

    cookie = create_session_cookie(body.username)
    response.set_cookie(
        key="MOLIOR_SESSION",
        value=cookie,
        httponly=True,
        max_age=302400,  # 1 week
        samesite="lax",
    )


@router.get("/logout", status_code=200)
def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie("MOLIOR_SESSION")


@router.get("/userinfo")
def userinfo(current_user: CurrentUser = Depends(authenticated)):
    """Return info about the currently authenticated user."""
    return {
        "username": current_user.username,
        "user_id": current_user.user_id,
        "is_admin": current_user.is_admin,
    }
