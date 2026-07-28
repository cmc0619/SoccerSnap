from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from soccersnap.process.app import create_process_router
from soccersnap.process.pipeline import ProcessPipeline
from soccersnap.protocol.checksum import sha256_file
from soccersnap.protocol.manifests import create_manifest
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.rig.recorder import RecorderFleet


@pytest.fixture()
def pipeline(isolated_settings) -> ProcessPipeline:
    return ProcessPipeline(
        sessions_dir=isolated_settings.staging_dir / "sessions",
        media_dir=isolated_settings.media_dir,
        recordings_dir=isolated_settings.recordings_dir,
    )


@pytest.fixture()
def process_client(fresh_db, pipeline, fake_clips):
    app = FastAPI()
    router = create_process_router(pipeline, FleetCoordinator(RecorderFleet(base_dir=pipeline.recordings_dir)))
    assert router.pipeline is pipeline
    assert router.coordinator is not None
    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def clip(tmp_path: Path) -> tuple[Path, str]:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"soccersnap-upload-bytes")
    return media, sha256_file(media)


def _upload(client: TestClient, headers: dict, clip: tuple[Path, str], **overrides):
    media, digest = clip
    data = {
        "session_id": "GAME_UPLOAD_001",
        "camera_id": "CAM_L",
        "checksum": digest,
    }
    data.update({k: v for k, v in overrides.items() if v is not None})
    with media.open("rb") as handle:
        return client.post(
            "/api/v1/upload",
            headers=headers,
            data=data,
            files={"file": ("clip.mp4", handle, "video/mp4")},
        )


def test_health_is_public(process_client, pipeline):
    body = process_client.get("/api/v1/health").json()
    assert body["status"] == "healthy"
    assert body["sessions_dir"] == str(pipeline.sessions_dir)


def test_upload_requires_ops(process_client, clip):
    assert _upload(process_client, {}, clip).status_code == 401


def test_upload_stores_and_confirms(process_client, ops_headers, clip, pipeline):
    media, digest = clip
    res = _upload(process_client, ops_headers, clip)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["checksum_verified"] is True
    assert body["checksum_sha256"] == digest
    stored = pipeline.sessions_dir / "GAME_UPLOAD_001" / "CAM_L" / "recording.mp4"
    assert stored.read_bytes() == media.read_bytes()
    # Temp staging area is cleaned up after the upload completes.
    assert not list((pipeline.sessions_dir.parent / "uploads").glob("*/*.mp4"))

    confirmed = process_client.post(
        "/api/v1/upload/confirm",
        headers=ops_headers,
        json={"session_id": "GAME_UPLOAD_001", "camera_id": "CAM_L"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["checksum_sha256"] == digest


def test_upload_with_manifest_writes_manifest(process_client, ops_headers, clip, pipeline):
    media, digest = clip
    manifest = create_manifest(
        session_id="GAME_UPLOAD_001",
        camera_id="CAM_C",
        media_path=media,
        duration_sec=3.0,
    )
    res = _upload(
        process_client,
        ops_headers,
        clip,
        camera_id="CAM_C",
        manifest=manifest.model_dump_json(),
    )
    assert res.status_code == 200, res.text
    assert (pipeline.sessions_dir / "GAME_UPLOAD_001" / "CAM_C" / "manifest.json").exists()


def test_upload_rejects_invalid_ids(process_client, ops_headers, clip):
    bad_camera = _upload(process_client, ops_headers, clip, camera_id="CAM_Q")
    assert bad_camera.status_code == 400
    assert bad_camera.json()["detail"] == "Invalid camera_id"

    bad_session = _upload(process_client, ops_headers, clip, session_id="../escape")
    assert bad_session.status_code == 400


def test_upload_rejects_checksum_mismatch(process_client, ops_headers, clip):
    res = _upload(process_client, ops_headers, clip, checksum="0" * 64)
    assert res.status_code == 400
    assert "Checksum mismatch" in res.json()["detail"]


def test_upload_enforces_size_cap(process_client, ops_headers, clip, isolated_settings, monkeypatch):
    monkeypatch.setattr(isolated_settings, "max_upload_bytes", 4)
    res = _upload(process_client, ops_headers, clip)
    assert res.status_code == 413
    assert "exceeds max size" in res.json()["detail"]


def test_upload_confirm_missing_recording_returns_404(process_client, ops_headers):
    res = process_client.post(
        "/api/v1/upload/confirm",
        headers=ops_headers,
        json={"session_id": "GAME_MISSING", "camera_id": "CAM_L"},
    )
    assert res.status_code == 404


def test_upload_confirm_rejects_invalid_ids(process_client, ops_headers):
    res = process_client.post(
        "/api/v1/upload/confirm",
        headers=ops_headers,
        json={"session_id": "GAME_OK", "camera_id": "CAM_Q"},
    )
    assert res.status_code == 400


def test_process_requires_ops_and_validates_ids(process_client, ops_headers):
    assert process_client.post("/api/v1/process", json={"session_id": "GAME_1"}).status_code == 401
    bad = process_client.post("/api/v1/process", headers=ops_headers, json={"session_id": "bad/id"})
    assert bad.status_code == 400


def test_process_unknown_session_returns_404(process_client, ops_headers):
    res = process_client.post(
        "/api/v1/process",
        headers=ops_headers,
        json={"session_id": "GAME_UNKNOWN"},
    )
    assert res.status_code == 404
    assert "No camera assets" in res.json()["detail"]


def test_process_from_rig_requires_all_three_cameras(process_client, ops_headers, pipeline):
    fleet = RecorderFleet(base_dir=pipeline.recordings_dir, simulate=True)
    fleet.start("GAME_PARTIAL_001")
    fleet.stop(duration_sec=2.0)
    # Drop two cameras so stitching preconditions fail.
    for cam in ("CAM_C", "CAM_R"):
        (pipeline.recordings_dir / f"GAME_PARTIAL_001_{cam}.json").unlink()

    res = process_client.post(
        "/api/v1/process/from-rig",
        headers=ops_headers,
        json={"session_id": "GAME_PARTIAL_001"},
    )
    assert res.status_code == 409
    assert "CAM_L, CAM_C, and CAM_R" in res.json()["detail"]


def test_sessions_listing(process_client, ops_headers, clip):
    assert process_client.get("/api/v1/sessions").status_code == 401
    assert process_client.get("/api/v1/sessions", headers=ops_headers).json() == {"sessions": []}

    _upload(process_client, ops_headers, clip)
    listed = process_client.get("/api/v1/sessions", headers=ops_headers).json()["sessions"]
    assert listed == ["GAME_UPLOAD_001"]


def test_router_creates_default_pipeline(fresh_db, isolated_settings):
    router = create_process_router()
    assert router.pipeline.sessions_dir == isolated_settings.staging_dir / "sessions"
    assert router.coordinator is None
