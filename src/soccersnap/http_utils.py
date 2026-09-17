"""Translate domain-level validation errors into FastAPI responses."""

from __future__ import annotations

from fastapi import HTTPException

from soccersnap.protocol.ids import InvalidIdError, validate_camera_id, validate_session_id


def validated_ids(
    session_id: str | None = None,
    camera_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Validate the ids that reach the filesystem, answering 400 on bad input."""
    try:
        sid = validate_session_id(session_id) if session_id is not None else None
        cam = validate_camera_id(camera_id) if camera_id is not None else None
    except InvalidIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sid, cam
