from __future__ import annotations

import pytest
from fastapi import HTTPException

from soccersnap.protocol.ids import validate_camera_id, validate_session_id
from soccersnap.protocol.offload import OffloadError, store_upload


def test_validate_session_rejects_path_traversal():
    with pytest.raises(HTTPException):
        validate_session_id("../evil")
    with pytest.raises(HTTPException):
        validate_session_id("GAME/1")
    assert validate_session_id("GAME_20260728_120000") == "GAME_20260728_120000"


def test_validate_camera_id():
    assert validate_camera_id("CAM_C") == "CAM_C"
    with pytest.raises(HTTPException):
        validate_camera_id("CAM_X")


def test_store_upload_rejects_pathful_ids(tmp_path):
    media = tmp_path / "x.mp4"
    media.write_bytes(b"abc")
    with pytest.raises(OffloadError):
        store_upload(
            sessions_dir=tmp_path / "sessions",
            session_id="../escape",
            camera_id="CAM_L",
            source_file=media,
            checksum_hex="0" * 64,
        )
