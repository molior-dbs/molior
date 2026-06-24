"""
API v2 router — aggregates all /api2/ sub-routers.

Each sub-module mirrors a file in molior/api2/.
"""

from fastapi import APIRouter

from .v2 import admin, build, mirror, project, projectversion, sourcerepository, token, user

router = APIRouter()

router.include_router(admin.router)
router.include_router(build.router)
router.include_router(mirror.router)
router.include_router(project.router)
router.include_router(projectversion.router)
router.include_router(sourcerepository.router)
router.include_router(token.router)
router.include_router(user.router)
