"""
/api2/build/{build_id}  DELETE + abort
/api2/project/{project_id}/{projectversion_id}/build/{build_id}  DELETE
Replaces molior/api2/build.py + the build delete in projectversion.py
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_role
from ...db import get_db
from ....logger import logger
from ....model.build import Build
from ....model.projectversion import ProjectVersion
from ....molior.queues import enqueue_aptly

router = APIRouter(prefix="/api2", tags=["builds"])

ACTIVE_STATES = {"scheduled", "building", "needs_publish", "publishing"}


def _collect_build_tree(build):
    """Return (topbuild, flat list of all builds in tree) or raise HTTPException."""
    topbuild = None
    builds = []
    if build.buildtype == "deb":
        topbuild = build.parent.parent
        builds.extend([build.parent, build.parent.parent])
        for b in build.parent.children:
            builds.append(b)
    elif build.buildtype == "source":
        topbuild = build.parent
        builds.extend([build, build.parent])
        for b in build.children:
            builds.append(b)
    elif build.buildtype == "build":
        topbuild = build
        builds.append(build)
        for b in build.children:
            builds.append(b)
            for c in b.children:
                builds.append(c)
    if not topbuild:
        raise HTTPException(status_code=400,
                            detail="Build of type %s cannot be deleted" % build.buildtype)
    return topbuild, builds


@router.delete("/build/{build_id}")
async def delete_build(
    build_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found", build_id)
        raise HTTPException(status_code=404, detail="Build not found")

    topbuild, builds = _collect_build_tree(build)

    for srcbuild in topbuild.children:
        for debbuild in srcbuild.children:
            if debbuild.projectversion and debbuild.projectversion.is_locked:
                raise HTTPException(status_code=400,
                                    detail="Build from locked projectversion cannot be deleted")
            if debbuild.buildstate in ACTIVE_STATES:
                raise HTTPException(status_code=400,
                                    detail="Build in state %s cannot be deleted" % debbuild.buildstate)

    for b in builds:
        b.is_deleted = True
    db.commit()

    await enqueue_aptly({"delete_build": [topbuild.id]})
    return "Build is being deleted"


@router.post("/build/{build_id}/abort")
async def abort_build(
    build_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found", build_id)
        raise HTTPException(status_code=404, detail="Build not found")

    topbuild = None
    srcbuild = None
    if build.buildtype == "deb":
        topbuild = build.parent.parent
        srcbuild = build.parent
    elif build.buildtype == "source":
        topbuild = build.parent
        srcbuild = build
    elif build.buildtype == "build":
        topbuild = build
        srcbuild = build.children[0]
    else:
        raise HTTPException(status_code=404,
                            detail="Build type '%s' cannot be aborted" % build.buildtype)

    if srcbuild.sourcerepository is None:
        raise HTTPException(status_code=404, detail="External build uploads cannot be aborted")

    found = any(
        deb.buildstate in ("building", "needs_build") for deb in srcbuild.children
    )
    if not found:
        raise HTTPException(status_code=404, detail="No running deb builds found")

    logger.info("aborting build %d", topbuild.id)
    await enqueue_aptly({"abort": [topbuild.id]})
    return "Abort initiated"


@router.delete("/project/{project_id}/{projectversion_id}/build/{build_id}")
async def delete_projectversion_build(
    project_id: str,
    projectversion_id: str,
    build_id: int,
    current_user: CurrentUser = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    projectversion = _get_projectversion(project_id, projectversion_id, db)
    if not projectversion:
        raise HTTPException(status_code=400, detail="Projectversion not found")
    if projectversion.project.is_mirror:
        raise HTTPException(status_code=400,
                            detail="Cannot delete build on project which is a mirror")
    if projectversion.is_locked:
        raise HTTPException(status_code=400,
                            detail="Cannot delete build on a locked projectversion")

    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        logger.error("build %d not found", build_id)
        raise HTTPException(status_code=404, detail="Build not found")

    topbuild, builds = _collect_build_tree(build)

    for srcbuild in topbuild.children:
        for debbuild in srcbuild.children:
            if debbuild.projectversion.id != projectversion.id:
                raise HTTPException(status_code=400,
                                    detail="Builds for multiple projectversions cannot be deleted")
            if debbuild.projectversion and debbuild.projectversion.is_locked:
                raise HTTPException(status_code=400,
                                    detail="Build from locked projectversion cannot be deleted")
            if debbuild.buildstate in ACTIVE_STATES:
                raise HTTPException(status_code=400,
                                    detail="Build in state %s cannot be deleted" % debbuild.buildstate)

    for b in builds:
        b.is_deleted = True
    db.commit()

    await enqueue_aptly({"delete_build": [topbuild.id]})
    return "Build is being deleted"


def _get_projectversion(project_id: str, projectversion_id: str, db: Session):
    from sqlalchemy import func
    from ....model.project import Project
    pv = db.query(ProjectVersion).join(Project).filter(
        func.lower(Project.name) == project_id.lower(),
        func.lower(ProjectVersion.name) == projectversion_id.lower(),
        Project.is_mirror.is_(False),
    ).first()
    return pv
