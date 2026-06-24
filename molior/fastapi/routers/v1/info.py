"""
/api/info/*
"""

from fastapi import APIRouter, Depends

from ...auth import authenticated, CurrentUser
from ....molior.configuration import Configuration

router = APIRouter(tags=["info"])


@router.get("/api/info/aptlyhostname")
def get_aptly_hostname(_: CurrentUser = Depends(authenticated)):
    return Configuration().aptly.get("host")
