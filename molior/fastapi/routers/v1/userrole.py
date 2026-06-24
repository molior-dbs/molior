"""
/api/userroles
"""

from fastapi import APIRouter

from ....model.userrole import USER_ROLES

router = APIRouter(tags=["userroles"])


@router.get("/api/userroles")
def get_userroles():
    return USER_ROLES
