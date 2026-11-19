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
from ....model.build import Build, DATETIME_FORMAT
from ....model.projectversion import ProjectVersion
from ....molior.queues import enqueue_aptly, enqueue_task

router = APIRouter(prefix="/api2", tags=["builds"])

ACTIVE_STATES = {"scheduled", "building", "needs_publish", "publishing"}


@router.get("/build/{build_id}")
def get_build(
    build_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    maintainer = ""
    if build.maintainer:
        maintainer = "{} {}".format(build.maintainer.firstname, build.maintainer.surname)

    project = {}
    if build.projectversion:
        project = {
            "id": build.projectversion.project.id,
            "name": build.projectversion.project.name,
            "is_mirror": build.projectversion.project.is_mirror,
            "version": {
                "id": build.projectversion.id,
                "name": build.projectversion.name,
                "is_locked": build.projectversion.is_locked,
            },
        }

    data = {
        "id": build.id,
        "buildstate": build.buildstate,
        "buildtype": build.buildtype,
        "startstamp": build.startstamp.strftime(DATETIME_FORMAT) if build.startstamp else "",
        "endstamp": build.endstamp.strftime(DATETIME_FORMAT) if build.endstamp else "",
        "version": build.version,
        "maintainer": maintainer,
        "sourcename": build.sourcename,
        "can_rebuild": build.can_rebuild(None, db),
        "branch": build.ci_branch,
        "git_ref": build.git_ref,
        "architecture": build.architecture,
        "project": project,
        "parent_id": build.parent_id,
        "children": [{"id": c.id, "sourcename": c.sourcename} for c in build.children],
    }

    if build.sourcerepository:
        data["sourcerepository"] = {
            "name": build.sourcerepository.name,
            "url": build.sourcerepository.url,
            "id": build.sourcerepository.id,
        }

    if build.projectversion and build.projectversion.basemirror:
        bm = build.projectversion.basemirror
        bm_name = bm.project.name
        bm_version = bm.name
        arch = build.architecture or ""
        data["buildvariant"] = {
            "architecture": {"name": arch},
            "base_mirror": {"name": bm_name, "version": bm_version},
            "name": f"{bm_name}-{bm_version}/{arch}",
        }
    elif build.projectversion:
        data["buildvariant"] = {
            "architecture": {"name": build.architecture or ""},
            "base_mirror": {"name": "", "version": ""},
            "name": "",
        }

    return data


@router.put("/build/{build_id}")
async def rebuild_build(
    build_id: int,
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    # a successful chroot build (build images of a base mirror) can be rebuilt by an admin
    admin_chroot_rebuild = build.buildtype == "chroot" and build.buildstate == "successful"
    if admin_chroot_rebuild and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    if not admin_chroot_rebuild and not build.can_rebuild(None, db):
        raise HTTPException(status_code=400, detail="This build cannot be rebuilt")

    if build.buildtype == "build":
        return await _retry_top_build(build, db)

    if build.buildtype == "deb" and (not build.parent or build.parent.buildstate != "successful"):
        raise HTTPException(status_code=400, detail="The source package of this build is not built, retry the source build")

    logger.info("rebuilding build %d", build_id)
    oldstate = build.buildstate
    await build.set_needs_build()
    db.commit()

    await enqueue_task({"rebuild": [build_id, oldstate]})
    return "Rebuild triggered"


def _top_retry_plan(top):
    """
    Returns (sources, debs) of a top level build to retry, each a list of builds:
    - sources in build_failed or publish_failed (their debs are still new, they follow the source)
    - failed debs below a successful source package
    """
    failed = ("build_failed", "publish_failed")
    sources = []
    debs = []
    for src in top.children:
        if src.buildstate in failed:
            sources.append(src)
        elif src.buildstate == "successful":
            debs.extend(deb for deb in src.children if deb.buildstate in failed)
    return sources, debs


async def _retry_top_build(top, db):
    sources, debs = _top_retry_plan(top)
    if not sources and not debs:
        raise HTTPException(status_code=400, detail="No failed source or deb builds to retry")
    for deb in debs:
        if deb.projectversion and deb.projectversion.is_locked:
            raise HTTPException(status_code=400, detail="Build from locked projectversion cannot be rebuilt")

    logger.info("rebuilding %d source and %d deb builds of top build %d", len(sources), len(debs), top.id)
    tasks = []
    for build in sources + debs:
        oldstate = build.buildstate
        await build.set_needs_build()
        tasks.append([build.id, oldstate, False])

    # the top build is running again (a source retry does not do this by itself)
    top.endstamp = None
    await top.set_building()
    db.commit()

    for task in tasks:
        await enqueue_task({"rebuild": task})
    if debs:
        await enqueue_task({"schedule": []})
    return "Rebuild triggered"


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
