from __future__ import annotations

from pathlib import Path

import pytest

from soccersnap.config import Settings


def _hardened(**overrides) -> Settings:
    base = dict(
        demo_mode=False,
        secret_key="unique-secret",
        ops_api_key="unique-ops",
        admin_password="unique-admin",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_demo_mode_skips_secret_validation():
    Settings(_env_file=None, demo_mode=True).validate_runtime_secrets()


def test_hardened_settings_accept_unique_secrets():
    _hardened().validate_runtime_secrets()


@pytest.mark.parametrize("placeholder", ["", "change-me-in-production", "soccersnap-dev-secret"])
def test_placeholder_secret_key_rejected(placeholder: str):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _hardened(secret_key=placeholder).validate_runtime_secrets()


@pytest.mark.parametrize("placeholder", ["", "change-me-ops-key", "soccersnap-ops"])
def test_placeholder_ops_key_rejected(placeholder: str):
    with pytest.raises(RuntimeError, match="OPS_API_KEY"):
        _hardened(ops_api_key=placeholder).validate_runtime_secrets()


@pytest.mark.parametrize("placeholder", ["", "soccersnap"])
def test_placeholder_admin_password_rejected(placeholder: str):
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        _hardened(admin_password=placeholder).validate_runtime_secrets()


def test_derived_dirs_and_ensure_dirs(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert settings.recordings_dir == tmp_path / "data" / "recordings"
    assert settings.staging_dir == tmp_path / "data" / "staging"
    assert settings.media_dir == tmp_path / "data" / "media"

    settings.ensure_dirs()
    for path in (settings.data_dir, settings.recordings_dir, settings.staging_dir, settings.media_dir):
        assert path.is_dir()

    # Idempotent.
    settings.ensure_dirs()


def test_env_prefix_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SOCCERSNAP_PORT", "8123")
    monkeypatch.setenv("SOCCERSNAP_DATA_DIR", str(tmp_path / "env-data"))
    settings = Settings(_env_file=None)
    assert settings.port == 8123
    assert settings.data_dir == tmp_path / "env-data"
