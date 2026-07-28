"""Safe identifier validation for filesystem paths."""

from __future__ import annotations

import re

from fastapi import HTTPException

# GAME_YYYYMMDD_HHMMSS or custom alnum/underscore/hyphen labels
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CAMERA_IDS = frozenset({"CAM_L", "CAM_C", "CAM_R"})


def validate_session_id(session_id: str) -> str:
    if not session_id or not _SESSION_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return session_id


def validate_camera_id(camera_id: str) -> str:
    if camera_id not in _CAMERA_IDS:
        raise HTTPException(status_code=400, detail="Invalid camera_id")
    return camera_id
