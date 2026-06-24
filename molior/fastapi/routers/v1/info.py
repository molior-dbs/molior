"""
/api/info/aptlyhostname
Replaces molior/api/info.py
"""

from fastapi import APIRouter, Depends

from ...auth import CurrentUser, authenticated
from ....molior.configuration import Configuration

router = APIRouter(prefix="/api/info", tags=["info"])


@router.get("/aptlyhostname")
def aptly_hostname(current_user: CurrentUser = Depends(authenticated)):
    return {"hostname": Configuration().aptly_server.get("hostname", "")}
