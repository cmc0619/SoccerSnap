from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from soccersnap import __version__
from soccersnap.config import Settings
from soccersnap.demo.app import create_demo_app
from soccersnap.process import pipeline as pipeline_mod


@pytest.fixture()
def stub_stitch(monkeypatch: pytest.MonkeyPatch):
    def _stitch(camera_paths: list[Path], output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"stitched")
        return output

    monkeypatch.setattr(pipeline_mod, "stitch_hstack", _stitch)


@pytest.fixture()
def client(fresh_db, fake_clips, stub_stitch):
    with TestClient(create_demo_app()) as c:
        yield c


def login(client: TestClient) -> None:
    res = client.post(
        "/api/portal/login",
        json={"username": "parent", "password": "parent", "team_code": "SNAP26"},
    )
    assert res.status_code == 200, res.text


def test_create_demo_app_refuses_placeholder_secrets(monkeypatch: pytest.MonkeyPatch, fresh_db):
    from soccersnap.demo import app as demo_app

    monkeypatch.setattr(demo_app, "settings", Settings(_env_file=None, demo_mode=False))
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        demo_app.create_demo_app()


def test_root_and_static_surfaces(client: TestClient):
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert client.get("/field/").status_code == 200
    assert client.get("/watch/").status_code == 200


def test_demo_info_exposes_seed_without_secrets(client: TestClient):
    body = client.get("/api/demo/info").json()
    assert body["version"] == __version__
    assert body["seed"]["team_code"] == "SNAP26"
    assert body["endpoints"]["watch"] == "/watch/"
    assert "ops_api_key" not in body


def test_run_match_requires_ops(client: TestClient):
    assert client.post("/api/demo/run-match").status_code == 401


def test_run_match_produces_ready_game_and_media(client: TestClient, ops_headers):
    res = client.post(
        "/api/demo/run-match",
        headers=ops_headers,
        params={"delay_sec": 0.0, "duration_sec": 2.0, "opponent": "Harbor FC"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["start"]["success"] is True
    assert len(body["stop"]["manifests"]) == 3
    assert body["processed"]["status"] == "ready"

    login(client)
    media_name = Path(body["processed"]["video_path"]).name
    media = client.get(f"/media/{media_name}")
    assert media.status_code == 200
    assert media.headers["content-type"] == "video/mp4"


def test_run_match_conflicts_when_already_recording(client: TestClient, ops_headers):
    assert client.post(
        "/api/v1/coordinator/start", headers=ops_headers, json={"delay_sec": 0.0}
    ).status_code == 200
    conflict = client.post("/api/demo/run-match", headers=ops_headers, params={"delay_sec": 0.0})
    assert conflict.status_code == 409


def test_media_requires_login(client: TestClient):
    assert client.get("/media/anything.mp4").status_code == 401


def test_media_rejects_traversal_names(client: TestClient):
    login(client)
    # Backslash is percent-encoded so the client does not normalize it away.
    for name in ("..%5Csecret.mp4", ".hidden"):
        assert client.get(f"/media/{name}").status_code == 400, name


def test_media_missing_file_and_unlinked_file(client: TestClient, isolated_settings):
    login(client)
    assert client.get("/media/absent.mp4").status_code == 404

    orphan = isolated_settings.media_dir / "orphan.mp4"
    orphan.write_bytes(b"not linked to a game")
    res = client.get("/media/orphan.mp4")
    assert res.status_code == 404
    assert res.json()["detail"] == "Media not linked to a game"


def test_media_non_mp4_uses_octet_stream(client: TestClient, isolated_settings, ops_headers):
    processed = client.post(
        "/api/demo/run-match",
        headers=ops_headers,
        params={"delay_sec": 0.0, "duration_sec": 2.0},
    ).json()["processed"]
    login(client)

    # Point the game at a non-mp4 asset to exercise the generic media type branch.
    from soccersnap.db import SessionLocal
    from soccersnap.models import Game

    assert SessionLocal is not None
    db = SessionLocal()
    try:
        game = db.query(Game).filter_by(session_id=processed["session_id"]).one()
        game.video_path = "/media/clip.bin"
        db.commit()
    finally:
        db.close()
    (isolated_settings.media_dir / "clip.bin").write_bytes(b"binary")

    res = client.get("/media/clip.bin")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
