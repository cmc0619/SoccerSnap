from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from soccersnap.protocol import gates
from soccersnap.protocol.gates import (
    BATTERY_CRITICAL,
    TEMP_LIMIT_C,
    all_gates,
    battery_safe,
    camera_present,
    free_space_ok,
    run_preflight,
    storage_writable,
    sync_ok,
    temperature_safe,
)


def test_camera_present_simulated():
    report = camera_present(simulate=True)
    assert report.ok is True
    assert report.reason == "Simulated camera online"


def test_camera_present_real_device(tmp_path: Path):
    device = tmp_path / "video0"
    device.write_text("", encoding="utf-8")
    assert camera_present(device).ok is True

    missing = camera_present(tmp_path / "nope")
    assert missing.ok is False
    assert "Camera device missing" in (missing.reason or "")


def test_storage_writable_ok_and_cleanup(tmp_path: Path):
    target = tmp_path / "recordings"
    assert storage_writable(target).ok is True
    assert not (target / ".soccersnap-write-test").exists()


def test_storage_writable_failure(tmp_path: Path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file in the way", encoding="utf-8")
    report = storage_writable(blocker)
    assert report.ok is False
    assert "Storage not writable" in (report.reason or "")


def test_free_space_ok_and_low(tmp_path: Path):
    ok = free_space_ok(tmp_path, minimum_gb=0.0001)
    assert ok.ok is True
    assert "GB free" in (ok.reason or "")

    low = free_space_ok(tmp_path, minimum_gb=10_000_000.0)
    assert low.ok is False
    assert "Low disk" in (low.reason or "")


def test_free_space_inspection_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(_path):
        raise OSError("no stat for you")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    report = free_space_ok(tmp_path, minimum_gb=1.0)
    assert report.ok is False
    assert "Disk inspection failed" in (report.reason or "")


def test_temperature_simulated_paths():
    assert temperature_safe(simulate=True).ok is True
    hot = temperature_safe(simulate=True, simulated_c=TEMP_LIMIT_C + 1)
    assert hot.ok is False
    assert "Overheating" in (hot.reason or "")


def test_temperature_from_sensor_file(tmp_path: Path):
    sensor = tmp_path / "temp"
    sensor.write_text("48200\n", encoding="utf-8")
    cool = temperature_safe(sensor)
    assert cool.ok is True
    assert cool.reason == "48.2C"

    sensor.write_text("90000", encoding="utf-8")
    assert temperature_safe(sensor).ok is False

    sensor.write_text("not-a-number", encoding="utf-8")
    unreadable = temperature_safe(sensor)
    assert unreadable.ok is False
    assert unreadable.reason == "Temperature read failed"


def test_temperature_missing_sensor_is_not_blocking(tmp_path: Path):
    report = temperature_safe(tmp_path / "absent")
    assert report.ok is True
    assert report.reason == "Temperature sensor unavailable"


def test_battery_simulated_paths():
    assert battery_safe(simulate=True).ok is True
    dead = battery_safe(simulate=True, simulated_percent=BATTERY_CRITICAL)
    assert dead.ok is False
    assert "critically low" in (dead.reason or "")


def test_battery_from_sensor_file(tmp_path: Path):
    capacity = tmp_path / "capacity"
    capacity.write_text("77\n", encoding="utf-8")
    charged = battery_safe(capacity)
    assert charged.ok is True
    assert charged.reason == "77%"

    capacity.write_text("3", encoding="utf-8")
    assert battery_safe(capacity).ok is False

    capacity.write_text("full", encoding="utf-8")
    unreadable = battery_safe(capacity)
    assert unreadable.ok is False
    assert unreadable.reason == "Battery read failed"


def test_battery_missing_sensor_is_not_blocking(tmp_path: Path):
    report = battery_safe(tmp_path / "absent")
    assert report.ok is True
    assert report.reason == "Battery sensor unavailable"


def test_sync_ok_within_and_beyond_limit():
    assert sync_ok(-1.5).ok is True
    drifted = sync_ok(9.0)
    assert drifted.ok is False
    assert "exceeds" in (drifted.reason or "")


def test_all_gates_covers_every_subsystem(tmp_path: Path):
    reports = all_gates(tmp_path, minimum_gb=0.0001, simulate=True)
    assert [r.name for r in reports] == [
        "camera",
        "storage",
        "disk",
        "temperature",
        "battery",
        "sync",
    ]
    assert all(r.ok for r in reports)


def test_run_preflight_reports_peers_and_blocking_disk(tmp_path: Path):
    result = run_preflight(tmp_path, minimum_gb=10_000_000.0, simulate=True)
    assert result["ok"] is False
    assert [b["name"] for b in result["blocking"]] == ["disk"]
    assert result["peers_online"] == ["CAM_L", "CAM_C", "CAM_R"]
    assert {r["name"] for r in result["reports"]} >= {"peer_sync_CAM_L", "peer_sync_CAM_R"}


def test_run_preflight_peer_reason_includes_camera_when_in_sync(tmp_path: Path):
    result = run_preflight(
        tmp_path,
        minimum_gb=0.0001,
        simulate=True,
        peer_offsets_ms={"CAM_C": 0.0},
    )
    assert result["ok"] is True
    peer = next(r for r in result["reports"] if r["name"] == "peer_sync_CAM_C")
    assert peer["reason"] == "0.00ms"


def test_gate_thresholds_are_stable():
    assert (gates.TEMP_LIMIT_C, gates.BATTERY_CRITICAL, gates.SYNC_LIMIT_MS) == (85.0, 10, 5.0)
