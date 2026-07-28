from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from soccersnap.protocol.checksum import sha256_file, verify_checksum
from soccersnap.protocol.gates import run_preflight
from soccersnap.protocol.manifests import create_manifest, load_manifest, mark_offloaded
from soccersnap.protocol.offload import BACKOFF_SECONDS, OffloadError, offload_with_retry, store_upload, confirm_upload
from soccersnap.protocol.query import parse_query, search_events
from soccersnap.protocol.schemas import Checksum, ConfirmRequest


def test_checksum_roundtrip(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"soccersnap")
    digest = sha256_file(f)
    assert verify_checksum(f, digest)
    assert not verify_checksum(f, "0" * 64)


def test_protocol_manifest_nested_and_flat(tmp_path: Path):
    media = tmp_path / "GAME_20260728_120000_CAM_C.mp4"
    media.write_bytes(b"fake-video-bytes")
    scheduled = datetime(2026, 7, 28, 12, 0, 2, tzinfo=timezone.utc)
    manifest = create_manifest(
        session_id="GAME_20260728_120000",
        camera_id="CAM_C",
        media_path=media,
        offset_ms=1.25,
        duration_sec=4.0,
        scheduled_start=scheduled,
    )
    path = manifest.write(tmp_path)
    loaded = load_manifest(path)
    assert loaded.version == "1.0"
    assert loaded.recording.id == "GAME_20260728_120000_CAM_C"
    assert loaded.recording.position == "center"
    assert loaded.timing.sync_offset_ms == 1.25
    assert loaded.timing.scheduled_start is not None
    flat = loaded.flat()
    assert flat["checksum"]["algo"] == "sha256"
    assert flat["offset_ms"] == 1.25
    assert flat["offloaded"] is False


def test_confirm_request_model():
    req = ConfirmRequest(
        session_id="GAME_1",
        camera_id="CAM_L",
        file="GAME_1_CAM_L.mp4",
        checksum=Checksum(algo="sha256", value="abc"),
    )
    assert req.checksum.algo == "sha256"


def test_offload_store_and_confirm(tmp_path: Path):
    sessions = tmp_path / "sessions"
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"1234567890")
    digest = sha256_file(media)
    manifest = create_manifest(
        session_id="GAME_X",
        camera_id="CAM_L",
        media_path=media,
        duration_sec=2,
    )
    uploaded = store_upload(
        sessions_dir=sessions,
        session_id="GAME_X",
        camera_id="CAM_L",
        source_file=media,
        checksum_hex=digest,
        manifest=manifest,
    )
    assert uploaded["checksum_verified"] is True
    confirmed = confirm_upload(sessions_dir=sessions, session_id="GAME_X", camera_id="CAM_L")
    assert confirmed["checksum_sha256"] == digest

    with pytest.raises(OffloadError):
        store_upload(
            sessions_dir=sessions,
            session_id="GAME_Y",
            camera_id="CAM_L",
            source_file=media,
            checksum_hex="0" * 64,
        )


def test_offload_retry_backoff_and_success(tmp_path: Path):
    media = tmp_path / "GAME_Z_CAM_R.mp4"
    media.write_bytes(b"retry-me")
    manifest = create_manifest(session_id="GAME_Z", camera_id="CAM_R", media_path=media, duration_sec=2)
    mpath = manifest.write(tmp_path)
    sleeps: list[float] = []
    attempts = {"n": 0}

    def upload_fn(path, checksum, man):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OffloadError("transient")
        return {"checksum_verified": True}

    def confirm_fn(session_id, camera_id):
        return {"checksum_sha256": man.checksum.value}

    # bind expected checksum via closure on final success path
    man = load_manifest(mpath)

    def confirm_ok(session_id, camera_id):
        return {"checksum_sha256": man.checksum.value}

    result = offload_with_retry(
        local_media=media,
        local_manifest_path=mpath,
        upload_fn=upload_fn,
        confirm_fn=confirm_ok,
        mark_dir=tmp_path,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert result["success"] is True
    assert result["attempts"] == 3
    assert sleeps == [5, 10]
    assert BACKOFF_SECONDS[0] == 0
    assert mark_offloaded  # imported presence
    reloaded = load_manifest(mpath)
    assert reloaded.offloaded is True


def test_preflight_simulate_ok(tmp_path: Path):
    result = run_preflight(tmp_path, minimum_gb=0.001, simulate=True)
    assert result["ok"] is True


def test_preflight_blocks_bad_peer_sync(tmp_path: Path):
    result = run_preflight(
        tmp_path,
        minimum_gb=0.001,
        simulate=True,
        peer_offsets_ms={"CAM_L": 0.5, "CAM_C": 0.0, "CAM_R": 12.0},
    )
    assert result["ok"] is False
    assert any(b["name"] == "peer_sync_CAM_R" for b in result["blocking"])


def test_query_parser_and_search():
    parsed = parse_query("show me saves by #1 in the first half")
    assert "save" in parsed.event_types
    assert parsed.jersey_number == 1
    assert parsed.half == 1
    events = [
        {"type": "save", "t_start_ms": 1000, "jersey_number": 1},
        {"type": "goal", "t_start_ms": 2000, "jersey_number": 9},
        {"type": "save", "t_start_ms": 50 * 60 * 1000, "jersey_number": 1},
    ]
    hits = search_events(events, parsed)
    assert len(hits) == 1
    assert hits[0]["t_start_ms"] == 1000
