"""
Aggregator router for all v1 (/api/) endpoints.
"""

from fastapi import APIRouter

from .v1 import (
    auth,
    build,
    buildstate,
    info,
    mirror,
    project,
    projectuserrole,
    projectversion,
    sourcerepository,
    status,
    user,
    userrole,
)

router = APIRouter()

router.include_router(auth.router)
router.include_router(build.router)
router.include_router(buildstate.router)
router.include_router(info.router)
router.include_router(mirror.router)
router.include_router(project.router)
router.include_router(projectuserrole.router)
router.include_router(projectversion.router)
router.include_router(sourcerepository.router)
router.include_router(status.router)
router.include_router(user.router)
router.include_router(userrole.router)
