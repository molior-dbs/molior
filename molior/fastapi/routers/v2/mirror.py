"""
/api2/mirror
Replaces molior/api2/mirror.py
"""

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...auth import CurrentUser, authenticated, require_admin
from ...db import get_db
from ...responses import PaginationParams
from ....logger import logger
from ....model.build import Build
from ....model.mirrorkey import MirrorKey
from ....model.project import Project
from ....model.projectversion import ProjectVersion
from ....molior.configuration import Configuration
from ....molior.queues import enqueue_aptly
from ....tools import array2db, db2array, escape_for_like

router = APIRouter(prefix="/api2", tags=["mirrors"])


def _lookup_mirror(name: str, version: str, db: Session):
    return (
        db.query(ProjectVersion)
        .join(Project, Project.id == ProjectVersion.project_id)
        .filter(
            Project.is_mirror.is_(True),
            func.lower(Project.name) == name.lower(),
            func.lower(ProjectVersion.name) == version.lower(),
        )
        .first()
    )


@router.get("/mirror/{name}/{version}")
def get_mirror(name: str, version: str, db: Session = Depends(get_db)):
    mirror = _lookup_mirror(name, version, db)
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")

    mirrorkey = db.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
    mirrorkeyurl = mirrorkey.keyurl if mirrorkey else ""
    mirrorkeyids = mirrorkey.keyids[1:-1] if mirrorkey and mirrorkey.keyids else ""
    mirrorkeyserver = mirrorkey.keyserver if mirrorkey else ""

    apt_url = mirror.get_apt_repo(url_only=True)
    basemirror_id = -1
    basemirror_url = ""
    basemirror_name = ""
    if not mirror.project.is_basemirror and mirror.basemirror:
        basemirror_id = mirror.basemirror.id
        basemirror_url = mirror.basemirror.get_apt_repo(url_only=True)
        basemirror_name = (
            mirror.basemirror.project.name + "/" + mirror.basemirror.name
        )

    return {
        "id": mirror.id,
        "name": mirror.project.name,
        "version": mirror.name,
        "url": mirror.mirror_url,
        "basemirror_id": basemirror_id,
        "basemirror_url": basemirror_url,
        "basemirror_name": basemirror_name,
        "distribution": mirror.mirror_distribution,
        "components": mirror.mirror_components,
        "is_basemirror": mirror.project.is_basemirror,
        "architectures": db2array(mirror.mirror_architectures),
        "is_locked": mirror.is_locked,
        "with_sources": mirror.mirror_with_sources,
        "with_installer": mirror.mirror_with_installer,
        "project_id": mirror.project.id,
        "state": mirror.mirror_state,
        "apt_url": apt_url,
        "mirrorkeyurl": mirrorkeyurl,
        "mirrorkeyids": mirrorkeyids,
        "mirrorkeyserver": mirrorkeyserver,
        "external_repo": mirror.external_repo,
        "dependency_policy": mirror.dependency_policy,
        "mirrorfilter": mirror.mirror_filter,
    }


@router.get("/mirror/{name}/{version}/dependents")
def get_mirror_dependents(
    name: str,
    version: str,
    q: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(),
    current_user: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
):
    mirror = _lookup_mirror(name, version, db)
    if not mirror:
        raise HTTPException(status_code=400, detail="Mirror not found")

    dependents = []
    nb_results = 0
    if mirror.project.is_basemirror:
        query = db.query(ProjectVersion).filter(
            ProjectVersion.basemirror_id == mirror.id
        )
        if q:
            query = query.filter(
                ProjectVersion.fullname.ilike(f"%{escape_for_like(q)}%")
            )
        nb_results = query.count()
        query = pagination.apply(query)
        dependents = query.all()

    dependents = list(dependents) + list(mirror.dependents)
    nb_results += len(mirror.dependents)

    return {
        "total_result_count": nb_results,
        "results": [d.data() for d in dependents],
    }


@router.get("/mirror/{name}/{version}/aptsources", response_class=PlainTextResponse)
def get_mirror_aptsources(name: str, version: str, db: Session = Depends(get_db)):
    mirror = _lookup_mirror(name, version, db)
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public") or cfg.aptly.get("apt_url")
    keyfile = cfg.aptly.get("key")

    sources = f"# APT Sources for mirror {name} {version}\n"
    sources += f"# GPG-Key: {apt_url}/{keyfile}\n\n"
    if mirror.project.is_basemirror:
        sources += "{}\n".format(mirror.get_apt_repo())
    elif mirror.basemirror:
        sources += "{}\n".format(mirror.basemirror.get_apt_repo())
        sources += "{}\n".format(mirror.get_apt_repo())
    return sources


class CreateMirrorBody(BaseModel):
    mirrorname: str
    mirrorversion: str
    mirrortype: str
    basemirror: Optional[str] = ""
    external: Optional[bool] = False
    mirrorurl: Optional[str] = ""
    mirrordist: Optional[str] = ""
    mirrorcomponents: Optional[str] = ""
    architectures: Optional[List[str]] = []
    mirrorsrc: Optional[bool] = False
    mirrorinst: Optional[bool] = False
    mirrorkeyurl: Optional[str] = ""
    mirrorkeyids: Optional[str] = ""
    mirrorkeyserver: Optional[str] = ""
    dependencylevel: Optional[str] = "strict"
    mirrorfilter: Optional[str] = ""


@router.post("/mirror")
async def create_mirror(
    body: CreateMirrorBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mirrorname = body.mirrorname.strip()
    mirrorversion = body.mirrorversion.strip()
    mirrortype = body.mirrortype.strip()
    basemirror = body.basemirror.strip()
    external_repo = body.external
    mirrorurl = body.mirrorurl.strip()
    mirrordist = body.mirrordist.strip()
    mirrorcomponents = re.split(r"[, ]", body.mirrorcomponents.strip()) if body.mirrorcomponents else []
    architectures = body.architectures or []
    mirrorsrc = body.mirrorsrc
    mirrorinst = body.mirrorinst
    mirrorkeyurl = body.mirrorkeyurl.strip()
    mirrorkeyids = body.mirrorkeyids.strip()
    mirrorkeyserver = body.mirrorkeyserver.strip()
    dependency_policy = body.dependencylevel.strip()
    mirrorfilter = body.mirrorfilter.strip()

    existing = db.query(ProjectVersion).join(Project).filter(
        func.lower(ProjectVersion.name) == mirrorversion.lower(),
        func.lower(Project.name) == mirrorname.lower(),
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Mirror {mirrorname}/{mirrorversion} already exists",
        )

    basemirror_id = None
    if mirrortype == "2":
        base_project, base_version = basemirror.split("/")
        bm_entry = (
            db.query(ProjectVersion)
            .join(Project, Project.id == ProjectVersion.project_id)
            .filter(
                Project.is_mirror.is_(True),
                func.lower(Project.name) == base_project.lower(),
                func.lower(ProjectVersion.name) == base_version.lower(),
            )
            .first()
        )
        if not bm_entry:
            raise HTTPException(status_code=400, detail="Invalid basemirror")
        basemirror_id = bm_entry.id

    is_basemirror = mirrortype == "1"
    if is_basemirror:
        dependency_policy = "strict"

    if mirrorkeyurl:
        mirrorkeyids = []
        mirrorkeyserver = ""
    elif mirrorkeyids:
        mirrorkeyurl = ""
        mirrorkeyids = re.split(r"[, ]", mirrorkeyids)
    else:
        mirrorkeyurl = ""
        mirrorkeyids = []
        mirrorkeyserver = ""

    if mirrordist == "/":
        mirrordist = "./"

    mirror_project = db.query(Project).filter(
        func.lower(Project.name) == mirrorname.lower(),
        Project.is_mirror.is_(True),
    ).first()
    if not mirror_project:
        mirror_project = Project(name=mirrorname, is_mirror=True, is_basemirror=is_basemirror)
        db.add(mirror_project)

    mirror = ProjectVersion(
        name=mirrorversion,
        project=mirror_project,
        mirror_url=mirrorurl,
        mirror_distribution=mirrordist,
        mirror_components=",".join(mirrorcomponents),
        mirror_architectures=array2db(architectures),
        mirror_with_sources=mirrorsrc,
        mirror_with_installer=mirrorinst,
        mirror_state="new",
        basemirror_id=basemirror_id,
        external_repo=external_repo,
        dependency_policy=dependency_policy,
        mirror_filter=mirrorfilter,
    )
    db.add(mirror)
    db.commit()

    mirrorkey = MirrorKey(
        projectversion_id=mirror.id,
        keyurl=mirrorkeyurl,
        keyids=array2db(mirrorkeyids),
        keyserver=mirrorkeyserver,
    )
    db.add(mirrorkey)

    build = Build(
        version=mirrorversion,
        git_ref=None,
        ci_branch=None,
        is_ci=False,
        sourcename=mirrorname,
        buildstate="new",
        buildtype="mirror",
        sourcerepository=None,
        maintainer=None,
        projectversion_id=mirror.id,
    )
    db.add(build)
    db.commit()
    build.log_state("created")
    await build.build_added()

    await enqueue_aptly({"init_mirror": [mirror.id]})
    return {"build_id": build.id}


class EditMirrorBody(BaseModel):
    mirrortype: str
    basemirror: Optional[str] = ""
    mirrorurl: Optional[str] = ""
    mirrordist: Optional[str] = ""
    mirrorcomponents: Optional[str] = ""
    architectures: Optional[List[str]] = []
    mirrorsrc: Optional[bool] = False
    mirrorinst: Optional[bool] = False
    mirrorkeyurl: Optional[str] = ""
    mirrorkeyids: Optional[str] = ""
    mirrorkeyserver: Optional[str] = ""
    dependencylevel: Optional[str] = "strict"
    mirrorfilter: Optional[str] = ""


@router.put("/mirror/{name}/{version}")
async def update_mirror(
    name: str,
    version: str,
    body: EditMirrorBody,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mirror = db.query(ProjectVersion).join(Project).filter(
        ProjectVersion.project_id == Project.id,
        func.lower(ProjectVersion.name) == version.lower(),
        func.lower(Project.name) == name.lower(),
    ).first()
    if not mirror:
        raise HTTPException(status_code=400, detail=f"Mirror not found {name}/{version}")

    mirrorkey = db.query(MirrorKey).filter(MirrorKey.projectversion_id == mirror.id).first()
    if not mirrorkey:
        raise HTTPException(status_code=400, detail=f"Mirror keys not found for mirror {mirror.id}")

    if mirror.is_locked:
        raise HTTPException(status_code=400, detail="Mirror is locked")

    mirrortype = body.mirrortype.strip()
    basemirror = body.basemirror.strip()
    mirrorurl = body.mirrorurl.strip()
    mirrordist = body.mirrordist.strip()
    architectures = body.architectures or []
    mirrorsrc = body.mirrorsrc
    mirrorinst = body.mirrorinst
    mirrorkeyurl = body.mirrorkeyurl.strip()
    mirrorkeyids = body.mirrorkeyids.strip()
    mirrorkeyserver = body.mirrorkeyserver.strip()
    dependency_policy = body.dependencylevel.strip()
    mirrorfilter = body.mirrorfilter.strip()

    if mirrordist == "/":
        mirrordist = "./"

    if basemirror:
        bm_name, bm_version = basemirror.split("/")
        bm = db.query(ProjectVersion).join(Project).filter(
            func.lower(Project.name) == bm_name.lower(),
            func.lower(ProjectVersion.name) == bm_version.lower(),
        ).first()
        if not bm:
            raise HTTPException(status_code=400, detail=f"Basemirror not found: {basemirror}")
        mirror.basemirror = bm

    mirror.mirror_url = mirrorurl
    mirror.mirror_distribution = mirrordist
    mirror.mirror_components = body.mirrorcomponents.strip() if body.mirrorcomponents else ""
    mirror.mirror_architectures = "{" + ", ".join(architectures) + "}"
    mirror.mirror_with_sources = mirrorsrc
    mirror.mirror_with_installer = mirrorinst
    mirror.is_basemirror = mirrortype == "1"
    mirror.mirror_filter = mirrorfilter
    if mirrortype == "2":
        mirror.dependency_policy = dependency_policy

    if mirrorkeyurl:
        mirrorkeyids_list = []
        mirrorkeyserver = ""
    elif mirrorkeyids:
        mirrorkeyurl = ""
        mirrorkeyids_list = re.split(r"[, ]", mirrorkeyids)
    else:
        mirrorkeyurl = ""
        mirrorkeyids_list = []
        mirrorkeyserver = ""

    mirrorkey.keyurl = mirrorkeyurl
    mirrorkey.keyids = array2db(mirrorkeyids_list)
    mirrorkey.keyserver = mirrorkeyserver
    db.commit()

    if mirror.mirror_state == "init_error":
        await enqueue_aptly({"init_mirror": [mirror.id]})
    else:
        await enqueue_aptly({"update_mirror": [mirror.id]})
    return "Mirror update started"


@router.delete("/mirror/{name}/{version}")
async def delete_mirror(
    name: str,
    version: str,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mirror = db.query(ProjectVersion).join(Project).filter(
        ProjectVersion.project_id == Project.id,
        func.lower(ProjectVersion.name) == version.lower(),
        func.lower(Project.name) == name.lower(),
        Project.is_mirror.is_(True),
    ).first()
    if not mirror:
        raise HTTPException(status_code=400, detail=f"Mirror not found {name}/{version}")

    mirrorname = f"{mirror.project.name}-{mirror.name}"

    if mirror.sourcerepositories:
        logger.warning("error deleting mirror '%s': referenced by source repositories", mirrorname)
        raise HTTPException(
            status_code=412,
            detail=f"Error deleting mirror {mirrorname}: still referenced from source repositories",
        )
    if mirror.dependents:
        logger.warning("error deleting mirror '%s': referenced by project versions", mirrorname)
        raise HTTPException(
            status_code=412,
            detail=f"Error deleting mirror {mirrorname}: still referenced from project versions",
        )
    if mirror.project.is_basemirror:
        dependents = db.query(ProjectVersion).filter(
            ProjectVersion.basemirror_id == mirror.id
        ).all()
        if dependents:
            logger.warning("error deleting mirror '%s': used as basemirror", mirrorname)
            raise HTTPException(
                status_code=412,
                detail=(
                    f"Error deleting mirror {mirrorname}: "
                    "still used as base mirror by one or more project versions"
                ),
            )

    mirror.is_deleted = True
    db.commit()
    await enqueue_aptly({"delete_mirror": [mirror.id]})
    return f"Successfully deleted mirror: {mirrorname}"
