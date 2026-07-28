from __future__ import annotations

from pathlib import Path

import pytest

from soccersnap.config import settings
from soccersnap.rig.recorder import RecorderFleet

OPS_KEY = "test-ops-key"


@pytest.fixture()
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the global settings singleton at a throwaway data dir + sqlite file."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(settings, "ops_api_key", OPS_KEY)
    monkeypatch.setattr(settings, "demo_mode", True)
    settings.ensure_dirs()
    return settings


@pytest.fixture()
def fresh_db(isolated_settings):
    from soccersnap import db as dbmod

    monkey_engine = dbmod._engine
    monkey_session = dbmod.SessionLocal
    dbmod._engine = None
    dbmod.SessionLocal = None
    dbmod.init_db(isolated_settings.database_url)
    yield dbmod
    dbmod._engine = monkey_engine
    dbmod.SessionLocal = monkey_session


@pytest.fixture()
def ops_headers():
    return {"X-SoccerSnap-Key": OPS_KEY}


@pytest.fixture()
def fake_clips(monkeypatch: pytest.MonkeyPatch):
    """Replace FFmpeg clip synthesis with tiny deterministic files."""

    def _write(self: RecorderFleet, path: Path, duration_sec: float, label: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"soccersnap-{label}-{duration_sec}".encode())

    monkeypatch.setattr(RecorderFleet, "_write_simulated_clip", _write)


@pytest.fixture()
def fleet(tmp_path: Path, fake_clips) -> RecorderFleet:
    return RecorderFleet(base_dir=tmp_path / "recordings", simulate=True)
