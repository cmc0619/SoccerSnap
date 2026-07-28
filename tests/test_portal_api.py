from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from soccersnap.demo.seed import seed_demo
from soccersnap.models import Game, GameEvent, Membership, Team, User
from soccersnap.portal.app import create_portal_router
from soccersnap.portal.auth import hash_password


@pytest.fixture()
def seeded(fresh_db):
    with fresh_db.session_scope() as db:
        seed_demo(db)
        team = db.query(Team).filter_by(team_code="SNAP26").one()
        other = Team(name="Harbor FC", team_code="HRBR1")
        db.add(other)
        db.flush()
        outsider = User(username="outsider", password_hash=hash_password("outsider"), role="parent")
        db.add(outsider)
        db.flush()
        db.add(Membership(user_id=outsider.id, team_id=other.id, role="parent"))
        game = Game(session_id="GAME_PORTAL_001", team_id=team.id, opponent="Rivals", status="ready")
        other_game = Game(session_id="GAME_OTHER_001", team_id=other.id, opponent="Anyone")
        db.add_all([game, other_game])
        db.flush()
        db.add(
            GameEvent(
                game_id=game.id,
                type="save",
                t_start_ms=1000,
                t_end_ms=3500,
                confidence=0.9,
                jersey_number=1,
                label="Keeper save",
                payload_json=json.dumps({"source": "test"}),
            )
        )
        db.add(
            GameEvent(
                game_id=game.id,
                type="goal",
                t_start_ms=4000,
                t_end_ms=6500,
                confidence=0.9,
                jersey_number=9,
                label="Goal",
            )
        )
        db.flush()
        ids = {"team_id": team.id, "game_id": game.id, "other_game_id": other_game.id}
    return ids


@pytest.fixture()
def client(seeded, isolated_settings):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(create_portal_router())
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str = "parent", password: str | None = None, **body):
    payload = {"username": username, "password": password or username}
    payload.update(body)
    return client.post("/api/portal/login", json=payload)


def test_login_rejects_bad_credentials(client: TestClient):
    assert login(client, "parent", "wrong").status_code == 401
    assert login(client, "ghost", "ghost").status_code == 401


def test_login_unknown_team_code(client: TestClient):
    res = login(client, team_code="ZZZZZ")
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown team code"


def test_login_non_member_team_code(client: TestClient):
    res = login(client, team_code="HRBR1")
    assert res.status_code == 403


def test_login_without_team_code_picks_first_membership(client: TestClient):
    body = login(client).json()
    assert body["team_code"] == "SNAP26"
    assert body["role"] == "parent"
    assert client.get("/api/portal/me").json()["display_name"] == "Alex Parent"


def test_admin_login_without_membership_has_no_team(client: TestClient):
    body = login(client, "admin", "soccersnap").json()
    assert body["role"] == "admin"
    assert body["team_code"] is None


def test_logout_ends_session(client: TestClient):
    login(client)
    assert client.post("/api/portal/logout").json() == {"ok": True}
    assert client.get("/api/portal/me").status_code == 401


def test_team_lookup_paths(client: TestClient):
    login(client)
    ok = client.get("/api/portal/teams/SNAP26")
    assert ok.status_code == 200
    assert ok.json()["age_group"] == "U12"
    assert client.get("/api/portal/teams/NOPE1").status_code == 404
    assert client.get("/api/portal/teams/HRBR1").status_code == 403


def test_admin_can_read_any_team(client: TestClient):
    login(client, "admin", "soccersnap")
    assert client.get("/api/portal/teams/HRBR1").status_code == 200


def test_games_scoped_to_membership(client: TestClient, seeded):
    login(client)
    games = client.get("/api/portal/games").json()["games"]
    assert [g["session_id"] for g in games] == ["GAME_PORTAL_001"]
    assert games[0]["event_count"] == 2

    assert client.get("/api/portal/games", params={"team_code": "ZZZZZ"}).json() == {"games": []}
    assert client.get("/api/portal/games", params={"team_code": "HRBR1"}).status_code == 403


def test_admin_sees_all_games(client: TestClient):
    login(client, "admin", "soccersnap")
    sessions = {g["session_id"] for g in client.get("/api/portal/games").json()["games"]}
    assert sessions == {"GAME_PORTAL_001", "GAME_OTHER_001"}


def test_game_detail_and_access_control(client: TestClient, seeded):
    login(client)
    detail = client.get(f"/api/portal/games/{seeded['game_id']}").json()
    assert [e["type"] for e in detail["events"]] == ["save", "goal"]
    assert detail["events"][0]["payload"] == {"source": "test"}
    assert detail["events"][1]["payload"] == {}

    assert client.get("/api/portal/games/9999").status_code == 404
    assert client.get(f"/api/portal/games/{seeded['other_game_id']}").status_code == 403


def test_search_get_and_post(client: TestClient, seeded):
    login(client)
    hits = client.get("/api/portal/search", params={"q": "saves"}).json()
    assert [h["type"] for h in hits["results"]] == ["save"]
    assert hits["query"]["event_types"] == ["save"]

    scoped = client.post(
        "/api/portal/search",
        json={"q": "goals by #9", "game_id": seeded["game_id"]},
    ).json()
    assert [h["type"] for h in scoped["results"]] == ["goal"]


def test_search_rejects_unknown_and_foreign_games(client: TestClient, seeded):
    login(client)
    assert client.get("/api/portal/search", params={"q": "goals", "game_id": 9999}).status_code == 404
    denied = client.get(
        "/api/portal/search",
        params={"q": "goals", "game_id": seeded["other_game_id"]},
    )
    assert denied.status_code == 403


def test_clip_create_and_list(client: TestClient, seeded):
    login(client)
    created = client.post(
        "/api/portal/clips",
        json={"game_id": seeded["game_id"], "title": "Great save", "t_start_ms": 500, "t_end_ms": 3000},
    )
    assert created.status_code == 200, created.text
    assert created.json()["title"] == "Great save"

    clips = client.get("/api/portal/clips", params={"game_id": seeded["game_id"]}).json()["clips"]
    assert [c["title"] for c in clips] == ["Great save"]
    assert clips[0]["created_by"] == "parent"
    assert client.get("/api/portal/clips").json()["clips"] == clips


def test_clip_validation_and_access(client: TestClient, seeded):
    login(client)
    bad_range = client.post(
        "/api/portal/clips",
        json={"game_id": seeded["game_id"], "t_start_ms": 5000, "t_end_ms": 1000},
    )
    assert bad_range.status_code == 400

    assert client.post(
        "/api/portal/clips", json={"game_id": 9999, "t_start_ms": 0, "t_end_ms": 10}
    ).status_code == 404
    assert client.post(
        "/api/portal/clips",
        json={"game_id": seeded["other_game_id"], "t_start_ms": 0, "t_end_ms": 10},
    ).status_code == 403


def test_clip_listing_rejects_unknown_and_foreign_games(client: TestClient, seeded):
    login(client)
    assert client.get("/api/portal/clips", params={"game_id": 9999}).status_code == 404
    assert client.get(
        "/api/portal/clips", params={"game_id": seeded["other_game_id"]}
    ).status_code == 403


def test_endpoints_require_login(client: TestClient, seeded):
    for path in (
        "/api/portal/me",
        "/api/portal/teams/SNAP26",
        "/api/portal/games",
        f"/api/portal/games/{seeded['game_id']}",
        "/api/portal/clips",
    ):
        assert client.get(path).status_code == 401, path
