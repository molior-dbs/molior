"""
/api/login, /api/logout, /api/userinfo
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, create_session_cookie
from ...db import get_db
from ....auth.auth import Auth
from ....model.user import User
from ....molior.configuration import Configuration

router = APIRouter(tags=["auth"])


@router.post("/api/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    # Accept JSON regardless of Content-Type header, matching cirrina behaviour
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    username = (data.get("username") or "").lower().strip()
    password = data.get("password") or ""

    # Admin auth
    if username == "admin":
        cfg = Configuration()
        admin_pass = cfg.admin.get("admin_password") or cfg.admin.get("pass")
        if not admin_pass or password != admin_pass:
            raise HTTPException(status_code=400, detail="Login failed")
    else:
        if not Auth().login(username, password):
            raise HTTPException(status_code=400, detail="Login failed")

    cookie = create_session_cookie(username)
    response.set_cookie("molior_session", cookie, httponly=True, samesite="lax")
    return ""


@router.get("/api/logout")
@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("molior_session")
    return ""


@router.get("/api/userinfo")
def get_userinfo(
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    if current_user.username == "admin":
        return {"username": "admin", "user_id": -1, "is_admin": True}
    user = db.query(User).filter_by(username=current_user.username).first()
    if user:
        return {"username": user.username, "user_id": user.id, "is_admin": user.is_admin}
    return {"username": current_user.username, "user_id": -1, "is_admin": False}
