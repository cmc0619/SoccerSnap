from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from soccersnap.paths import UnsafePathError, free_gb, is_safe_name, resolve_within
from soccersnap.timeutils import iso_utc, seconds_until, utcnow


def test_is_safe_name():
    assert is_safe_name("GAME_1_CAM_L.mp4")
    assert not is_safe_name("")
    assert not is_safe_name("../escape")
    assert not is_safe_name("nested/name")
    assert not is_safe_name("back\\slash")
    assert not is_safe_name(".hidden")


def test_resolve_within(tmp_path: Path):
    assert resolve_within(tmp_path, "sessions", "CAM_L") == (tmp_path / "sessions" / "CAM_L").resolve()
    assert resolve_within(tmp_path) == tmp_path.resolve()
    with pytest.raises(UnsafePathError):
        resolve_within(tmp_path, "..", "escape")


def test_free_gb(tmp_path: Path):
    assert free_gb(tmp_path) > 0


def test_iso_utc_appends_z_and_assumes_utc():
    assert iso_utc(datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)) == "2026-07-28T12:00:00Z"
    assert iso_utc(datetime(2026, 7, 28, 12, 0)) == "2026-07-28T12:00:00Z"
    assert iso_utc(None) is None


def test_seconds_until():
    assert 0.0 < seconds_until(utcnow() + timedelta(seconds=5)) <= 5.0
    assert seconds_until(utcnow() - timedelta(seconds=5)) < 0.0
