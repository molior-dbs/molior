"""
/internal/buildupload/{token}  (file upload from build nodes)
/internal/buildlog/{token}     (WebSocket log stream from build nodes)
Replaces molior/api/upload.py
"""

from fastapi import APIRouter, Depends, UploadFile, WebSocket
from sqlalchemy.orm import Session

from ...db import get_db

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/buildupload/{token}")
async def build_upload(token: str, file: UploadFile, db: Session = Depends(get_db)):
    # TODO: validate token against BuildTask, write file to build output dir
    raise NotImplementedError


@router.websocket("/buildlog/{token}")
async def build_log(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    # TODO: accept connection, validate token, stream log lines to build log queue
    raise NotImplementedError
