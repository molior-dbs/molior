"""
API v1 router — aggregates all /api/ sub-routers.

Each sub-module mirrors a file in molior/api/.  Handlers are stubs today;
port them one module at a time from the originals.
"""

from fastapi import APIRouter

from .v1 import auth, build, buildstate, info, mirror, project, projectuserrole, projectversion
from .v1 import sourcerepository, status, upload, userrole, websocket

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
router.include_router(upload.router)
router.include_router(userrole.router)
router.include_router(websocket.router)
