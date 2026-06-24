"""
/api/buildstates
Replaces molior/api/buildstate.py
"""

from fastapi import APIRouter, Depends

from ...auth import CurrentUser, authenticated

router = APIRouter(prefix="/api", tags=["builds"])

BUILD_STATES = [
    "new", "cloning", "cloned", "clone_error",
    "building", "build_failed", "build_failed_upload", "successful",
    "needs_build", "scheduled", "already_failed", "already_built",
]


@router.get("/buildstates")
def get_buildstates(current_user: CurrentUser = Depends(authenticated)):
    return BUILD_STATES
