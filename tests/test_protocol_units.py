from __future__ import annotations

import json
from pathlib import Path

import pytest

from soccersnap.protocol import offload as offload_mod
from soccersnap.protocol.checksum import sha256_file, verify_checksum
from soccersnap.protocol.manifests import (
    create_manifest,
    list_manifests,
    load_manifest,
    mark_offloaded,
    parse_resolution,
)
from soccersnap.protocol.offload import (
    OffloadError,
    confirm_upload,
    offload_with_retry,
    store_upload,
)
from soccersnap.protocol.query import ParsedQuery, parse_query, search_events


@pytest.fixture()
def clip(tmp_path: Path) -> Path:
    media = tmp_path / "GAME_UNIT_001_CAM_L.mp4"
    media.write_bytes(b"unit-test-bytes")
    return media


def test_verify_checksum_rejects_other_algorithms(clip: Path):
    with pytest.raises(ValueError, match="Unsupported checksum algo"):
        verify_checksum(clip, "0" * 32, algo="md5")


def test_parse_resolution_falls_back_on_garbage():
    assert parse_resolution("640x480").model_dump() == {"width": 640, "height": 480}
    assert parse_resolution("not-a-resolution").model_dump() == {"width": 1280, "height": 720}


def test_load_manifest_normalizes_flat_manifest(tmp_path: Path, clip: Path):
    flat = {
        "session_id": "GAME_UNIT_001",
        "camera_id": "CAM_L",
        "file": clip.name,
        "size_bytes": clip.stat().st_size,
        "resolution": "1920x1080",
        "duration": 5.5,
        "offset_ms": 2.5,
        "checksum": {"algo": "sha256", "value": sha256_file(clip)},
        "start_time_local": "2026-07-28T12:00:00Z",
        "offloaded": True,
    }
    path = tmp_path / "flat.json"
    path.write_text(json.dumps(flat), encoding="utf-8")

    manifest = load_manifest(path)
    assert manifest.recording.id == "GAME_UNIT_001_CAM_L"
    assert manifest.recording.position == "left"
    assert manifest.video.resolution.width == 1920
    assert manifest.video.duration_sec == 5.5
    assert manifest.timing.sync_offset_ms == 2.5
    assert manifest.timing.end_time == "2026-07-28T12:00:00Z"
    assert manifest.offloaded is True


def test_mark_offloaded_missing_manifest_returns_none(tmp_path: Path):
    assert mark_offloaded(tmp_path, "GAME_MISSING", "CAM_L") is None


def test_list_manifests_skips_unreadable_files(tmp_path: Path, clip: Path):
    create_manifest(session_id="GAME_UNIT_001", camera_id="CAM_L", media_path=clip).write(tmp_path)
    (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")
    assert [m.camera_id.value for m in list_manifests(tmp_path)] == ["CAM_L"]


def test_list_manifests_missing_directory(tmp_path: Path):
    assert list_manifests(tmp_path / "absent") == []


@pytest.mark.parametrize(
    ("session_id", "camera_id"),
    [("", "CAM_L"), ("GAME_1", ""), ("GAME/1", "CAM_L"), ("GAME_1", "CAM_L/x"), ("GAME_1", "CAM_Q")],
)
def test_store_upload_rejects_unsafe_or_unknown_ids(tmp_path: Path, clip: Path, session_id, camera_id):
    with pytest.raises(OffloadError):
        store_upload(
            sessions_dir=tmp_path / "sessions",
            session_id=session_id,
            camera_id=camera_id,
            source_file=clip,
            checksum_hex=sha256_file(clip),
        )


def test_store_upload_detects_post_copy_corruption(tmp_path: Path, clip: Path, monkeypatch):
    digest = sha256_file(clip)
    monkeypatch.setattr(offload_mod, "sha256_file", lambda path, **kw: "f" * 64)
    with pytest.raises(OffloadError, match="Post-copy checksum mismatch"):
        store_upload(
            sessions_dir=tmp_path / "sessions",
            session_id="GAME_UNIT_001",
            camera_id="CAM_L",
            source_file=clip,
            checksum_hex=digest,
        )
    assert not list((tmp_path / "sessions" / "GAME_UNIT_001" / "CAM_L").glob(".recording.*"))


def test_store_upload_overwrites_existing_recording(tmp_path: Path, clip: Path):
    sessions = tmp_path / "sessions"
    for payload in (b"first-take", b"second-take"):
        clip.write_bytes(payload)
        result = store_upload(
            sessions_dir=sessions,
            session_id="GAME_UNIT_001",
            camera_id="CAM_L",
            source_file=clip,
            checksum_hex=sha256_file(clip),
        )
    assert (sessions / "GAME_UNIT_001" / "CAM_L" / "recording.mp4").read_bytes() == b"second-take"
    assert result["recording_id"] == "GAME_UNIT_001_CAM_L"


def test_confirm_upload_missing_recording(tmp_path: Path):
    with pytest.raises(OffloadError, match="Recording not found"):
        confirm_upload(sessions_dir=tmp_path, session_id="GAME_UNIT_001", camera_id="CAM_L")


def _manifest_path(tmp_path: Path, clip: Path) -> Path:
    manifest = create_manifest(
        session_id="GAME_UNIT_001",
        camera_id="CAM_L",
        media_path=clip,
        duration_sec=2.0,
    )
    return manifest.write(tmp_path)


def test_offload_retry_gives_up_after_max_attempts(tmp_path: Path, clip: Path):
    path = _manifest_path(tmp_path, clip)
    sleeps: list[float] = []

    def always_fails(*_args):
        raise OffloadError("server down")

    with pytest.raises(OffloadError, match="failed after 3 attempts"):
        offload_with_retry(
            local_media=clip,
            local_manifest_path=path,
            upload_fn=always_fails,
            confirm_fn=lambda *_: {},
            mark_dir=tmp_path,
            max_attempts=3,
            sleep_fn=sleeps.append,
        )
    assert sleeps == [5, 10]
    assert load_manifest(path).offloaded is False


def test_offload_retry_wraps_unexpected_exceptions(tmp_path: Path, clip: Path):
    path = _manifest_path(tmp_path, clip)

    def network_blip(*_args):
        raise ConnectionResetError("connection reset")

    with pytest.raises(OffloadError, match="connection reset"):
        offload_with_retry(
            local_media=clip,
            local_manifest_path=path,
            upload_fn=network_blip,
            confirm_fn=lambda *_: {},
            mark_dir=tmp_path,
            max_attempts=1,
            sleep_fn=lambda _s: None,
        )


def test_offload_retry_requires_server_side_verification(tmp_path: Path, clip: Path):
    path = _manifest_path(tmp_path, clip)
    with pytest.raises(OffloadError, match="Server did not verify checksum"):
        offload_with_retry(
            local_media=clip,
            local_manifest_path=path,
            upload_fn=lambda *_: {"checksum_verified": False},
            confirm_fn=lambda *_: {},
            mark_dir=tmp_path,
            max_attempts=1,
            sleep_fn=lambda _s: None,
        )


def test_offload_retry_beyond_backoff_table_does_not_sleep(tmp_path: Path, clip: Path):
    path = _manifest_path(tmp_path, clip)
    sleeps: list[float] = []
    attempts = {"n": 0}
    digest = load_manifest(path).checksum.value

    def upload_fn(*_args):
        attempts["n"] += 1
        if attempts["n"] <= 5:
            raise OffloadError("still down")
        return {"checksum_verified": True}

    result = offload_with_retry(
        local_media=clip,
        local_manifest_path=path,
        upload_fn=upload_fn,
        confirm_fn=lambda *_: {"checksum_sha256": digest},
        mark_dir=tmp_path,
        max_attempts=6,
        sleep_fn=sleeps.append,
    )
    assert result["attempts"] == 6
    assert result["offloaded"] is True
    assert sleeps == [5, 10, 20, 40]


def test_parse_query_defaults_and_second_half():
    empty = parse_query("")
    assert empty.event_types == []
    assert (empty.jersey_number, empty.half) == (None, None)

    parsed = parse_query("free kicks in the 2nd half")
    assert parsed.event_types == ["free_kick"]
    assert parsed.half == 2


def test_search_events_accepts_raw_query_string():
    events = [{"type": "goal", "t_start_ms": 100}, {"type": "pass", "t_start_ms": 200}]
    assert search_events(events, "goals") == [events[0]]


def test_search_events_matches_jersey_from_payload():
    events = [
        {"type": "goal", "t_start_ms": 100, "payload": {"jersey_number": 9}},
        {"type": "goal", "t_start_ms": 200, "payload": {}},
    ]
    hits = search_events(events, "goals by #9")
    assert hits == [events[0]]


def test_search_events_falls_back_to_timestamp_ms_and_limit():
    events = [{"type": "goal", "timestamp_ms": 50 * 60 * 1000} for _ in range(5)]
    assert search_events(events, ParsedQuery(event_types=["goal"], half=1)) == []
    limited = search_events(events, ParsedQuery(event_types=["goal"], half=2, limit=2))
    assert len(limited) == 2
