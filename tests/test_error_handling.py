from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from soccersnap.media import FFmpegError, run_ffmpeg
from soccersnap.process.stitcher import stitch_hstack
from soccersnap.protocol.manifests import list_manifests, parse_resolution
from soccersnap.protocol.offload import OffloadError, offload_with_retry
from soccersnap.rig.recorder import RecorderError, RecorderFleet


def test_run_ffmpeg_reports_missing_binary():
    with pytest.raises(FFmpegError, match="not found"):
        run_ffmpeg(["soccersnap-no-such-ffmpeg"], timeout=5, context="Probe")


def test_run_ffmpeg_includes_stderr_tail(monkeypatch: pytest.MonkeyPatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=b"Invalid data found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(FFmpegError, match="Invalid data found"):
        run_ffmpeg(["ffmpeg"], timeout=5, context="Stitch out.mp4")


def test_stitch_failure_propagates_as_ffmpeg_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(234, args[0], stderr=b"hstack: incompatible sizes")

    monkeypatch.setattr(subprocess, "run", fake_run)
    clips = []
    for name in ("a.mp4", "b.mp4"):
        clip = tmp_path / name
        clip.write_bytes(b"x")
        clips.append(clip)
    with pytest.raises(FFmpegError, match="hstack: incompatible sizes"):
        stitch_hstack(clips, tmp_path / "out.mp4")


def test_list_manifests_logs_and_skips_corrupt(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    (tmp_path / "GAME_1_CAM_L.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert list_manifests(tmp_path) == []
    assert "Skipping unreadable manifest" in caplog.text


def test_parse_resolution_warns_on_fallback(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        block = parse_resolution("not-a-resolution")
    assert (block.width, block.height) == (1280, 720)
    assert "Unparseable resolution" in caplog.text


def test_failed_stop_clears_recording_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fleet = RecorderFleet(base_dir=tmp_path)
    fleet.start("GAME_20260101_120000")

    def boom(*args, **kwargs):
        raise FFmpegError("ffmpeg exited 1: encoder failure")

    monkeypatch.setattr(RecorderFleet, "_write_simulated_clip", boom)
    with pytest.raises(RecorderError, match="cameras failed to stop"):
        fleet.stop(duration_sec=2.0)
    # Fleet must be startable again instead of wedged in "recording".
    assert not any(node.recording for node in fleet.nodes.values())
    assert fleet.status()["recording"] is False


def test_cleanup_reports_undeletable_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fleet = RecorderFleet(base_dir=tmp_path)
    fleet.start("GAME_20260101_120000")
    manifests = fleet.stop(duration_sec=2.0)
    for manifest in manifests:
        manifest.offloaded = True
        manifest.write(tmp_path)

    def deny(self, *args, **kwargs):
        raise OSError("device busy")

    monkeypatch.setattr(Path, "unlink", deny)
    result = fleet.cleanup_offloaded()
    assert result["removed"] == []
    assert len(result["failed"]) == 6
    assert "device busy" in result["failed"][0]


def test_offload_retry_chains_last_error(tmp_path: Path):
    fleet = RecorderFleet(base_dir=tmp_path)
    fleet.start("GAME_20260101_120000")
    manifest = fleet.stop(duration_sec=2.0)[0]
    manifest_path = manifest.path_for(tmp_path)

    def upload_fn(*args, **kwargs):
        raise ConnectionError("uplink down")

    with pytest.raises(OffloadError) as excinfo:
        offload_with_retry(
            local_media=tmp_path / manifest.file_name,
            local_manifest_path=manifest_path,
            upload_fn=upload_fn,
            confirm_fn=lambda *args: {},
            mark_dir=tmp_path,
            max_attempts=2,
            sleep_fn=lambda _: None,
        )
    assert isinstance(excinfo.value.__cause__, ConnectionError)
    assert "uplink down" in str(excinfo.value)
