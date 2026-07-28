"""Watch UI regressions: CSS hidden cascade + portal session edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

WATCH_CSS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "soccersnap"
    / "web"
    / "watch"
    / "styles.css"
)


def test_watch_layout_rules_are_hidden_aware():
    """Author display:grid must not apply while [hidden] is set."""
    css = WATCH_CSS.read_text(encoding="utf-8")
    assert ".gate:not([hidden])" in css
    assert "#app:not([hidden])" in css
    # Unconditional layout display would reintroduce the login-gate bug.
    assert ".gate {\n  display: grid" not in css
    assert "#app {\n  display: grid" not in css


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOCCERSNAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOCCERSNAP_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SOCCERSNAP_OPS_API_KEY", "test-ops-key")
    from soccersnap.config import settings

    settings.data_dir = tmp_path / "data"
    settings.database_url = f"sqlite:///{tmp_path / 'test.db'}"
    settings.ops_api_key = "test-ops-key"
    settings.ensure_dirs()

    from soccersnap import db as dbmod

    dbmod._engine = None
    dbmod.SessionLocal = None
    dbmod.init_db(settings.database_url)

    from soccersnap.demo.app import create_demo_app

    app = create_demo_app()
    with TestClient(app) as c:
        yield c


def test_games_omit_bogus_null_team_code(client: TestClient):
    """String 'null' must not be treated as a team filter that empties results."""
    start = client.post(
        "/api/v1/coordinator/start",
        json={"delay_sec": 0.0},
        headers={"X-SoccerSnap-Key": "test-ops-key"},
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    client.post(
        "/api/v1/coordinator/stop",
        headers={"X-SoccerSnap-Key": "test-ops-key"},
        params={"duration_sec": 1.0},
    )
    processed = client.post(
        "/api/v1/process/from-rig",
        headers={"X-SoccerSnap-Key": "test-ops-key"},
        json={"session_id": session_id, "opponent": "Rivals"},
    )
    assert processed.status_code == 200, processed.text

    login = client.post(
        "/api/portal/login",
        json={"username": "parent", "password": "parent", "team_code": "SNAP26"},
    )
    assert login.status_code == 200

    ok = client.get("/api/portal/games")
    assert ok.status_code == 200
    assert len(ok.json()["games"]) >= 1

    bogus = client.get("/api/portal/games", params={"team_code": "null"})
    assert bogus.status_code == 200
    assert bogus.json()["games"] == []


def test_watch_gate_hides_after_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DOM smoke: #gate must not stay visible after a successful portal login."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import socket
    import threading
    import time
    import uvicorn

    monkeypatch.setenv("SOCCERSNAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOCCERSNAP_DATABASE_URL", f"sqlite:///{tmp_path / 'ui.db'}")
    monkeypatch.setenv("SOCCERSNAP_OPS_API_KEY", "test-ops-key")
    from soccersnap.config import settings

    settings.data_dir = tmp_path / "data"
    settings.database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    settings.ops_api_key = "test-ops-key"
    settings.ensure_dirs()

    from soccersnap import db as dbmod

    dbmod._engine = None
    dbmod.SessionLocal = None
    dbmod.init_db(settings.database_url)

    from soccersnap.demo.app import create_demo_app

    app = create_demo_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/watch/", wait_until="networkidle")
            assert page.locator("#gate").is_visible()
            page.locator('#loginForm button[type="submit"]').click()
            page.wait_for_selector("#app:not([hidden])")
            assert page.locator("#gate").is_hidden()
            assert page.locator("#app").is_visible()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
