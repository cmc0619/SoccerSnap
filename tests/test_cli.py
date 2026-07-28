from __future__ import annotations

import pytest

from soccersnap import __version__
from soccersnap.__main__ import main
from soccersnap.config import settings


def test_version_command_prints_version(capsys: pytest.CaptureFixture[str]):
    main(["version"])
    assert capsys.readouterr().out.strip() == __version__


def test_demo_command_uses_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    import uvicorn

    captured: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))

    main(["demo"])

    assert captured["app"] == "soccersnap.demo.app:create_demo_app"
    assert captured["factory"] is True
    assert captured["host"] == settings.host
    assert captured["port"] == settings.port
    assert captured["reload"] is False


def test_demo_command_overrides_host_and_port(monkeypatch: pytest.MonkeyPatch):
    import uvicorn

    captured: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))

    main(["demo", "--host", "127.0.0.1", "--port", "9999"])

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999


def test_missing_command_exits():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_unknown_command_exits():
    with pytest.raises(SystemExit):
        main(["not-a-command"])
