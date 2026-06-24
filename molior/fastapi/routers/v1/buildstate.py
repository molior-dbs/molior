"""
/api/buildstates
"""

from fastapi import APIRouter, Depends

from ...auth import authenticated, CurrentUser
from ....model.build import BUILD_STATES

router = APIRouter(tags=["builds"])


@router.get("/api/buildstates")
def get_buildstates(_: CurrentUser = Depends(authenticated)):
    return {"total_result_count": len(BUILD_STATES), "results": BUILD_STATES}
