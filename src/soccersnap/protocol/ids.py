"""Safe identifier validation for filesystem paths."""

from __future__ import annotations

import re

from soccersnap.paths import is_safe_name

# GAME_YYYYMMDD_HHMMSS or custom alnum/underscore/hyphen labels
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Left-to-right capture order; also the only accepted camera ids.
CAMERA_IDS: tuple[str, ...] = ("CAM_L", "CAM_C", "CAM_R")
_CAMERA_IDS = frozenset(CAMERA_IDS)


class InvalidIdError(ValueError):
    pass


def validate_session_id(session_id: str) -> str:
    if not session_id or not _SESSION_RE.fullmatch(session_id):
        raise InvalidIdError("Invalid session_id")
    if not is_safe_name(session_id):
        raise InvalidIdError("Invalid session_id")
    return session_id


def validate_camera_id(camera_id: str) -> str:
    if camera_id not in _CAMERA_IDS:
        raise InvalidIdError("Invalid camera_id")
    return camera_id
