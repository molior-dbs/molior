"""
/api/status, /api/status/maintenance, /api/nodes, /api/node/{machineID}
"""

from multiprocessing import cpu_count
from os import getloadavg
from os.path import expanduser
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psutil import disk_usage, virtual_memory
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...responses import PaginationParams

from ...auth import CurrentUser, require_admin
from ...db import get_db
from ....aptly.api import get_aptly_connection
from ....molior.backend import Backend
from ....molior.configuration import Configuration
from ....version import MOLIOR_VERSION

router = APIRouter(tags=["status"])


def _server_info():
    machine_id = None
    try:
        with open("/etc/machine-id") as f:
            machine_id = f.readline().strip()
    except IOError:
        pass

    with open("/proc/uptime") as f:
        uptime = float(f.readline().split()[0])

    return {
        "name": "molior server",
        "uptime_seconds": uptime,
        "load": list(getloadavg()),
        "cpu_cores": cpu_count(),
        "ram_used": virtual_memory().used,
        "ram_total": virtual_memory().total,
        "disk_used": disk_usage("/").used,
        "disk_total": disk_usage("/").total,
        "id": machine_id,
    }


@router.get("/api/status")
async def get_status(db: Session = Depends(get_db)):
    maintenance_mode = False
    maintenance_message = ""

    q = text("SELECT value FROM metadata WHERE name = :key")
    for row in db.execute(q, {"key": "maintenance_mode"}):
        if row[0] == "true":
            maintenance_mode = True
        break
    for row in db.execute(q, {"key": "maintenance_message"}):
        maintenance_message = row[0]
        break

    sshkey = ""
    try:
        with open(expanduser("~/.ssh/id_rsa.pub")) as f:
            sshkey = f.read()
    except Exception:
        pass

    aptly = get_aptly_connection()
    aptly_version = await aptly.version()

    cfg = Configuration()
    apt_url = cfg.aptly.get("apt_url_public") or cfg.aptly.get("apt_url")
    gpgurl = f"{apt_url}/{cfg.aptly.get('key')}"

    return {
        "version_molior_server": MOLIOR_VERSION,
        "version_aptly": aptly_version,
        "maintenance_message": maintenance_message,
        "maintenance_mode": maintenance_mode,
        "sshkey": sshkey,
        "gpgurl": gpgurl,
    }


class MaintenanceBody(BaseModel):
    maintenance_mode: Optional[str] = ""
    maintenance_message: Optional[str] = ""


@router.post("/api/status/maintenance")
def set_maintenance(
    body: MaintenanceBody,
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    status = {}
    if body.maintenance_mode != "":
        new_mode = "false" if body.maintenance_mode == "true" else "true"
        db.execute(
            text("UPDATE metadata SET value = :v WHERE name = :k"),
            {"k": "maintenance_mode", "v": new_mode},
        )
        db.commit()
        status["maintenance_mode"] = new_mode == "true"

    if body.maintenance_message != "":
        db.execute(
            text("UPDATE metadata SET value = :v WHERE name = :k"),
            {"k": "maintenance_message", "v": body.maintenance_message},
        )
        db.commit()
        status["maintenance_message"] = body.maintenance_message

    return status


@router.get("/api/nodes")
def get_nodes(
    q: Optional[str] = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    backend = Backend().get_backend()
    build_nodes = backend.get_nodes_info()

    results = [_server_info()]
    for node in build_nodes:
        if q and q.lower() not in node["name"].lower():
            continue
        results.append(node)

    results.sort(key=lambda n: n["name"])
    total = len(results)
    page = pagination.page
    size = pagination.page_size
    paged = results[size * (page - 1): size * page]
    return {"total_result_count": total, "results": paged}


@router.get("/api/node/{machine_id}")
def get_node(machine_id: str):
    backend = Backend().get_backend()
    for node in backend.get_nodes_info():
        if node["id"] == machine_id:
            return node
    raise HTTPException(status_code=404, detail="Node not found")
