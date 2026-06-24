"""
/api/userroles
Replaces molior/api/userrole.py
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["users"])

USER_ROLES = ["owner", "manager", "member"]


@router.get("/userroles")
def get_userroles():
    return USER_ROLES
