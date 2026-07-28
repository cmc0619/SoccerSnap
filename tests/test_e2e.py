from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


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


def ops_headers():
    return {"X-SoccerSnap-Key": "test-ops-key"}


def login(client: TestClient):
    res = client.post(
        "/api/portal/login",
        json={"username": "parent", "password": "parent", "team_code": "SNAP26"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_demo_info_and_login(client: TestClient):
    info = client.get("/api/demo/info")
    assert info.status_code == 200
    assert info.json()["product"] == "SoccerSnap"
    assert "ops_api_key" not in info.json()

    # Public info must not leak ops key; unlock requires admin basic auth.
    assert client.post("/api/demo/field-unlock").status_code == 401
    unlocked = client.post(
        "/api/demo/field-unlock",
        auth=("admin", "soccersnap"),
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["ops_api_key"] == "test-ops-key"

    # Unauthenticated portal access blocked
    denied = client.get("/api/portal/games")
    assert denied.status_code == 401

    login(client)
    games = client.get("/api/portal/games", params={"team_code": "SNAP26"})
    assert games.status_code == 200


def test_destructive_rig_requires_ops_auth(client: TestClient):
    bare = client.get("/api/v1/recordings")
    assert bare.status_code == 401
    ok = client.get("/api/v1/recordings", headers=ops_headers())
    assert ok.status_code == 200


def test_full_match_pipeline(client: TestClient):
    start = client.post("/api/v1/coordinator/start", json={"delay_sec": 0.0})
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["success"] is True
    assert body["scheduled_start"]
    session_id = body["session_id"]

    stop = client.post("/api/v1/coordinator/stop", params={"duration_sec": 2.5})
    assert stop.status_code == 200, stop.text
    assert stop.json()["session_id"] == session_id
    assert len(stop.json()["manifests"]) == 3

    flat = stop.json()["flat_manifests"][0]
    # Confirm without ops key must fail
    assert (
        client.post(
            "/api/v1/recordings/confirm",
            json={
                "session_id": flat["session_id"],
                "camera_id": flat["camera_id"],
                "file": flat["file"],
                "checksum": flat["checksum"],
            },
        ).status_code
        == 401
    )

    confirm = client.post(
        "/api/v1/recordings/confirm",
        headers=ops_headers(),
        json={
            "session_id": flat["session_id"],
            "camera_id": flat["camera_id"],
            "file": flat["file"],
            "checksum": flat["checksum"],
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["offloaded"] is True

    processed = client.post(
        "/api/v1/process/from-rig",
        headers=ops_headers(),
        json={"session_id": session_id, "opponent": "Harbor FC"},
    )
    assert processed.status_code == 200, processed.text
    pdata = processed.json()
    assert pdata["status"] == "ready"
    assert pdata["events"] > 0

    login(client)
    games = client.get("/api/portal/games", params={"team_code": "SNAP26"})
    assert games.status_code == 200
    assert any(g["session_id"] == session_id for g in games.json()["games"])

    game_id = next(g["id"] for g in games.json()["games"] if g["session_id"] == session_id)
    detail = client.get(f"/api/portal/games/{game_id}")
    assert detail.status_code == 200
    assert detail.json()["video_path"]

    search = client.get("/api/portal/search", params={"q": "saves", "game_id": game_id})
    assert search.status_code == 200
    assert len(search.json()["results"]) >= 1

    media_name = Path(detail.json()["video_path"]).name
    media = client.get(f"/media/{media_name}")
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("video/")

    # Logout then media denied
    client.post("/api/portal/logout")
    assert client.get(f"/media/{media_name}").status_code == 401
