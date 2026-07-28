from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from soccersnap.protocol.checksum import sha256_file
from soccersnap.protocol.manifests import CameraId, load_manifest
from soccersnap.protocol.schemas import Checksum, ConfirmRequest
from soccersnap.rig.framing import FramingQuality, assess_framing, score_to_quality
from soccersnap.rig.recorder import CameraNode, RecorderFleet, default_fleet


def _confirm_request(fleet: RecorderFleet, session_id: str, camera_id: str, **overrides) -> ConfirmRequest:
    manifest = load_manifest(fleet.base_dir / f"{session_id}_{camera_id}.json")
    body = {
        "session_id": session_id,
        "camera_id": camera_id,
        "file": manifest.file_name,
        "checksum": Checksum(algo="sha256", value=manifest.checksum.value),
    }
    body.update(overrides)
    return ConfirmRequest(**body)


def test_default_nodes_and_disk_status(fleet: RecorderFleet):
    assert set(fleet.nodes) == {"CAM_L", "CAM_C", "CAM_R"}
    disk = fleet.disk_status()
    assert disk.total_gb > 0
    assert disk.free_gb > 0
    assert disk.free_percent is not None
    assert disk.estimated_minutes_remaining is not None


def test_custom_nodes_are_preserved(tmp_path: Path):
    fleet = RecorderFleet(base_dir=tmp_path, nodes={"CAM_C": CameraNode(CameraId.CAM_C)})
    assert list(fleet.nodes) == ["CAM_C"]


def test_status_reports_per_camera_detail(fleet: RecorderFleet):
    status = fleet.status()
    assert status["recording"] is False
    assert status["session_id"] is None
    center = next(c for c in status["cameras"] if c["camera_id"] == "CAM_C")
    assert center["sync"]["role"] == "master"
    assert center["framing"]["quality"] == "excellent"
    assert center["scheduled_start"] is None
    left = next(c for c in status["cameras"] if c["camera_id"] == "CAM_L")
    assert left["sync"]["role"] == "client"


def test_start_marks_all_cameras_recording(fleet: RecorderFleet):
    scheduled = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    status = fleet.start("GAME_REC_001", scheduled_start=scheduled)
    assert status["recording"] is True
    assert status["session_id"] == "GAME_REC_001"
    assert all(c["scheduled_start"] == "2026-07-28T12:00:00Z" for c in status["cameras"])


def test_start_while_recording_raises(fleet: RecorderFleet):
    fleet.start("GAME_REC_001")
    with pytest.raises(RuntimeError, match="Already recording"):
        fleet.start("GAME_REC_002")


def test_stop_without_recording_raises(fleet: RecorderFleet):
    with pytest.raises(RuntimeError, match="Not recording"):
        fleet.stop()


def test_stop_writes_manifests_and_media(fleet: RecorderFleet):
    fleet.start("GAME_REC_001")
    manifests = fleet.stop(duration_sec=4.0)
    assert len(manifests) == 3
    for manifest in manifests:
        media = fleet.base_dir / manifest.file_name
        assert media.exists()
        assert manifest.checksum.value == sha256_file(media)
        assert manifest.video.duration_sec == 4.0
        assert manifest.device.software_version == fleet.software_version
    assert all(node.recording is False for node in fleet.nodes.values())


def test_stop_defaults_duration_to_elapsed_floor(fleet: RecorderFleet):
    fleet.start("GAME_REC_002")
    manifests = fleet.stop()
    assert all(m.video.duration_sec == 3.0 for m in manifests)


def test_recordings_listing_includes_sizes(fleet: RecorderFleet):
    fleet.start("GAME_REC_003")
    fleet.stop(duration_sec=2.0)
    listed = fleet.recordings()
    assert len(listed) == 3
    assert all(rec["exists"] is True and rec["size_bytes"] > 0 for rec in listed)
    assert all("manifest" in rec for rec in listed)


def test_recordings_listing_flags_missing_media(fleet: RecorderFleet):
    fleet.start("GAME_REC_004")
    manifests = fleet.stop(duration_sec=2.0)
    (fleet.base_dir / manifests[0].file_name).unlink()
    entry = next(r for r in fleet.recordings() if r["file"] == manifests[0].file_name)
    assert entry["exists"] is False
    assert entry["size_bytes"] == 0


def test_confirm_marks_offloaded(fleet: RecorderFleet):
    fleet.start("GAME_CONF_001")
    fleet.stop(duration_sec=2.0)
    marked = fleet.confirm(_confirm_request(fleet, "GAME_CONF_001", "CAM_L"))
    assert marked.offloaded is True
    assert load_manifest(fleet.base_dir / "GAME_CONF_001_CAM_L.json").offloaded is True


def test_confirm_missing_manifest_raises(fleet: RecorderFleet):
    request = ConfirmRequest(
        session_id="GAME_NONE",
        camera_id="CAM_L",
        file="GAME_NONE_CAM_L.mp4",
        checksum=Checksum(value="0" * 64),
    )
    with pytest.raises(FileNotFoundError, match="Manifest not found"):
        fleet.confirm(request)


def test_confirm_rejects_file_name_mismatch(fleet: RecorderFleet):
    fleet.start("GAME_CONF_002")
    fleet.stop(duration_sec=2.0)
    request = _confirm_request(fleet, "GAME_CONF_002", "CAM_L", file="somebody-elses.mp4")
    with pytest.raises(ValueError, match="File name does not match manifest"):
        fleet.confirm(request)


def test_confirm_requires_media_present(fleet: RecorderFleet):
    fleet.start("GAME_CONF_003")
    fleet.stop(duration_sec=2.0)
    request = _confirm_request(fleet, "GAME_CONF_003", "CAM_L")
    (fleet.base_dir / request.file).unlink()
    with pytest.raises(FileNotFoundError, match="Media missing"):
        fleet.confirm(request)


def test_confirm_rejects_unsupported_algorithm(fleet: RecorderFleet):
    fleet.start("GAME_CONF_004")
    fleet.stop(duration_sec=2.0)
    request = _confirm_request(fleet, "GAME_CONF_004", "CAM_L")
    request.checksum.algo = "md5"
    with pytest.raises(ValueError, match="Unsupported checksum algorithm"):
        fleet.confirm(request)


def test_confirm_rejects_checksum_mismatch(fleet: RecorderFleet):
    fleet.start("GAME_CONF_005")
    fleet.stop(duration_sec=2.0)
    request = _confirm_request(fleet, "GAME_CONF_005", "CAM_L")
    request.checksum.value = "0" * 64
    with pytest.raises(ValueError, match="refusing offload confirm"):
        fleet.confirm(request)


def test_cleanup_only_removes_offloaded(fleet: RecorderFleet):
    fleet.start("GAME_CLEAN_001")
    fleet.stop(duration_sec=2.0)
    fleet.confirm(_confirm_request(fleet, "GAME_CLEAN_001", "CAM_R"))

    removed = fleet.cleanup_offloaded()
    assert len(removed) == 2
    assert not (fleet.base_dir / "GAME_CLEAN_001_CAM_R.mp4").exists()
    assert (fleet.base_dir / "GAME_CLEAN_001_CAM_L.mp4").exists()
    assert fleet.cleanup_offloaded() == []


def test_default_fleet_uses_settings(isolated_settings):
    fleet = default_fleet()
    assert fleet.base_dir == isolated_settings.recordings_dir
    assert fleet.simulate is isolated_settings.simulate_hardware
    assert fleet.software_version == isolated_settings.software_version


@pytest.mark.parametrize(
    ("score", "quality", "tone"),
    [
        (0.95, FramingQuality.EXCELLENT, 880),
        (0.80, FramingQuality.GOOD, 740),
        (0.50, FramingQuality.PARTIAL, 520),
        (0.10, FramingQuality.NO_FIELD, 320),
    ],
)
def test_score_to_quality_tiers(score: float, quality: FramingQuality, tone: int):
    result = score_to_quality(score)
    assert result.quality is quality
    assert result.tone_hz == tone


def test_assess_framing_defaults_and_overrides():
    assert assess_framing("CAM_L").score == 0.91
    assert assess_framing("CAM_UNKNOWN").score == 0.8
    assert assess_framing("CAM_UNKNOWN", simulate=False).quality is FramingQuality.NO_FIELD
    assert assess_framing("CAM_L", score=0.5).quality is FramingQuality.PARTIAL
