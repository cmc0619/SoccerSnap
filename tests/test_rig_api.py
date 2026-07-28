from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from soccersnap.protocol.checksum import sha256_file
from soccersnap.rig.app import create_rig_app
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.rig.recorder import RecorderFleet


@pytest.fixture()
def rig(isolated_settings, fake_clips):
    fleet = RecorderFleet(base_dir=isolated_settings.recordings_dir, simulate=True)
    coordinator = FleetCoordinator(fleet)
    with TestClient(create_rig_app(coordinator)) as client:
        yield client, coordinator


def _record_session(client: TestClient, headers: dict, session_id: str = "GAME_TEST_001") -> dict:
    start = client.post(
        "/api/v1/coordinator/start",
        headers=headers,
        json={"session_id": session_id, "delay_sec": 0.0},
    )
    assert start.status_code == 200, start.text
    stop = client.post("/api/v1/coordinator/stop", headers=headers, params={"duration_sec": 2.0})
    assert stop.status_code == 200, stop.text
    return stop.json()


def test_health_and_status_are_public(rig):
    client, _ = rig
    health = client.get("/api/v1/health").json()
    assert health["status"] == "healthy"
    assert health["storage_free_gb"] > 0

    status = client.get("/api/v1/status").json()
    assert status["coordinator"] == "CAM_C"
    assert len(status["cameras"]) == 3
    assert client.get("/api/v1/coordinator/status").json() == status

    peers = client.get("/api/v1/coordinator/peers").json()["peers"]
    assert [p["camera_id"] for p in peers] == ["CAM_L", "CAM_C", "CAM_R"]
    assert [p["is_local"] for p in peers] == [False, True, False]


def test_coordinator_preflight_is_public(rig):
    client, _ = rig
    result = client.post("/api/v1/coordinator/preflight").json()
    assert result["ok"] is True
    assert result["peers"]


def test_coordinator_start_requires_ops(rig):
    client, _ = rig
    assert client.post("/api/v1/coordinator/start", json={"delay_sec": 0.0}).status_code == 401


def test_coordinator_start_rejects_bad_session_id(rig, ops_headers):
    client, _ = rig
    res = client.post(
        "/api/v1/coordinator/start",
        headers=ops_headers,
        json={"session_id": "../escape", "delay_sec": 0.0},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid session_id"


def test_coordinator_start_conflicts_when_already_recording(rig, ops_headers):
    client, _ = rig
    assert client.post(
        "/api/v1/coordinator/start", headers=ops_headers, json={"delay_sec": 0.0}
    ).status_code == 200
    conflict = client.post("/api/v1/coordinator/start", headers=ops_headers, json={"delay_sec": 0.0})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "Recording already in progress"


def test_coordinator_stop_without_recording_conflicts(rig, ops_headers):
    client, _ = rig
    conflict = client.post("/api/v1/coordinator/stop", headers=ops_headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Not recording"


def test_record_start_stop_aliases(rig, ops_headers):
    client, _ = rig
    started = client.post("/api/v1/record/start", headers=ops_headers, json={})
    assert started.status_code == 200
    assert started.json()["success"] is True
    stopped = client.post("/api/v1/record/stop", headers=ops_headers)
    assert stopped.status_code == 200
    assert len(stopped.json()["manifests"]) == 3


def test_record_start_rejects_bad_session_id(rig, ops_headers):
    client, _ = rig
    res = client.post("/api/v1/record/start", headers=ops_headers, json={"session_id": "bad/id"})
    assert res.status_code == 400


def test_record_start_honors_scheduled_start(rig, ops_headers):
    client, _ = rig
    scheduled = datetime.now(timezone.utc) + timedelta(seconds=0.2)
    res = client.post(
        "/api/v1/record/start",
        headers=ops_headers,
        json={"session_id": "GAME_SCHED_001", "scheduled_start": scheduled.isoformat()},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "GAME_SCHED_001"
    assert datetime.fromisoformat(body["scheduled_start"].replace("Z", "+00:00")) >= scheduled


def test_record_start_with_naive_past_scheduled_start(rig, ops_headers):
    client, _ = rig
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    res = client.post(
        "/api/v1/record/start",
        headers=ops_headers,
        json={"session_id": "GAME_PAST_001", "scheduled_start": past.isoformat()},
    )
    assert res.status_code == 200


def test_record_start_conflicts_when_recording(rig, ops_headers):
    client, _ = rig
    client.post("/api/v1/record/start", headers=ops_headers, json={})
    assert client.post("/api/v1/record/start", headers=ops_headers, json={}).status_code == 409


def test_framing_endpoint(rig):
    client, _ = rig
    body = client.get("/api/v1/framing/CAM_C").json()
    assert body == {
        "camera_id": "CAM_C",
        "quality": "excellent",
        "score": 0.96,
        "message": "Field framed cleanly",
        "tone_hz": 880,
    }


def test_recordings_listing_requires_ops(rig, ops_headers):
    client, _ = rig
    assert client.get("/api/v1/recordings").status_code == 401
    _record_session(client, ops_headers)
    listed = client.get("/api/v1/recordings", headers=ops_headers).json()["recordings"]
    assert len(listed) == 3
    assert all(rec["exists"] and rec["size_bytes"] > 0 for rec in listed)


def test_confirm_missing_manifest_returns_404(rig, ops_headers):
    client, _ = rig
    res = client.post(
        "/api/v1/recordings/confirm",
        headers=ops_headers,
        json={
            "session_id": "GAME_NOPE",
            "camera_id": "CAM_L",
            "file": "GAME_NOPE_CAM_L.mp4",
            "checksum": {"algo": "sha256", "value": "0" * 64},
        },
    )
    assert res.status_code == 404


def test_confirm_checksum_mismatch_returns_400(rig, ops_headers):
    client, _ = rig
    flat = _record_session(client, ops_headers)["flat_manifests"][0]
    res = client.post(
        "/api/v1/recordings/confirm",
        headers=ops_headers,
        json={
            "session_id": flat["session_id"],
            "camera_id": flat["camera_id"],
            "file": flat["file"],
            "checksum": {"algo": "sha256", "value": "0" * 64},
        },
    )
    assert res.status_code == 400
    assert "Checksum mismatch" in res.json()["detail"]


def test_cleanup_removes_offloaded_recordings(rig, ops_headers):
    client, coordinator = rig
    flat = _record_session(client, ops_headers)["flat_manifests"][0]
    confirm = client.post(
        "/api/v1/recordings/confirm",
        headers=ops_headers,
        json={
            "session_id": flat["session_id"],
            "camera_id": flat["camera_id"],
            "file": flat["file"],
            "checksum": flat["checksum"],
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["offloaded"] is True

    removed = client.post("/api/v1/recordings/cleanup", headers=ops_headers).json()["removed"]
    assert len(removed) == 2
    assert len(coordinator.fleet.recordings()) == 2


def test_recording_media_download(rig, ops_headers, isolated_settings):
    client, _ = rig
    stop = _record_session(client, ops_headers, session_id="GAME_MEDIA_001")
    flat = stop["flat_manifests"][0]
    path: Path = isolated_settings.recordings_dir / flat["file"]
    assert path.exists()

    res = client.get(
        f"/api/v1/recordings/GAME_MEDIA_001/{flat['camera_id']}/media",
        headers=ops_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "video/mp4"
    assert sha256_file(path) == flat["checksum"]["value"]


def test_recording_media_validation_and_missing(rig, ops_headers):
    client, _ = rig
    assert client.get("/api/v1/recordings/GAME_X/CAM_Q/media", headers=ops_headers).status_code == 400
    missing = client.get("/api/v1/recordings/GAME_MISSING/CAM_L/media", headers=ops_headers)
    assert missing.status_code == 404
    assert client.get("/api/v1/recordings/GAME_MISSING/CAM_L/media").status_code == 401
