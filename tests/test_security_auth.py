from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from soccersnap.config import settings
from soccersnap.db import get_session
from soccersnap.models import Membership, Team, User
from soccersnap.portal.auth import hash_password
from soccersnap.security import (
    PortalPrincipal,
    login_session,
    logout_session,
    require_ops,
    require_portal_user,
    verify_user_password,
)

from conftest import OPS_KEY


@pytest.fixture()
def seeded(fresh_db):
    with fresh_db.session_scope() as db:
        team = Team(name="SoccerSnap FC", team_code="SNAP26")
        other = Team(name="Harbor FC", team_code="HRBR1")
        db.add_all([team, other])
        db.flush()
        parent = User(username="parent", password_hash=hash_password("parent"), role="parent")
        admin = User(username="admin", password_hash=hash_password("soccersnap"), role="admin")
        loner = User(username="loner", password_hash=hash_password("loner"), role="parent")
        db.add_all([parent, admin, loner])
        db.flush()
        db.add(Membership(user_id=parent.id, team_id=team.id, role="parent"))
        db.flush()
        ids = {"team_id": team.id, "other_team_id": other.id, "parent_id": parent.id}
    return ids


@pytest.fixture()
def app_client(seeded, isolated_settings):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.get("/ops", dependencies=[Depends(require_ops)])
    def ops():
        return {"ok": True}

    @app.post("/login/{username}")
    def login(username: str, request: Request, team_code: str | None = None, db=Depends(get_session)):
        user = db.query(User).filter_by(username=username).one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="no user")
        team = db.query(Team).filter_by(team_code=team_code).one_or_none() if team_code else None
        login_session(request, user, team)
        return {"ok": True}

    @app.post("/logout")
    def logout(request: Request):
        logout_session(request)
        return {"ok": True}

    @app.post("/login-code-only/{username}")
    def login_code_only(username: str, request: Request, team_code: str, db=Depends(get_session)):
        user = db.query(User).filter_by(username=username).one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="no user")
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["team_code"] = team_code
        return {"ok": True}

    @app.post("/login-stale")
    def login_stale(request: Request):
        request.session["user_id"] = 9999
        return {"ok": True}

    @app.get("/me")
    def me(principal: PortalPrincipal = Depends(require_portal_user)):
        return {
            "username": principal.user.username,
            "team_code": principal.team.team_code if principal.team else None,
            "team_ids": principal.team_ids,
        }

    with TestClient(app) as client:
        yield client


def test_ops_accepts_header_key(app_client: TestClient):
    assert app_client.get("/ops", headers={"X-SoccerSnap-Key": OPS_KEY}).status_code == 200


def test_ops_rejects_missing_and_wrong_credentials(app_client: TestClient):
    denied = app_client.get("/ops")
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Basic"
    assert app_client.get("/ops", headers={"X-SoccerSnap-Key": "nope"}).status_code == 401
    assert app_client.get("/ops", auth=("admin", "wrong")).status_code == 401


def test_ops_accepts_admin_basic_auth(app_client: TestClient):
    res = app_client.get("/ops", auth=(settings.admin_user, settings.admin_password))
    assert res.status_code == 200


def test_ops_accepts_ops_key_as_basic_password(app_client: TestClient):
    assert app_client.get("/ops", auth=("anyone", OPS_KEY)).status_code == 200


def test_portal_user_requires_session(app_client: TestClient):
    assert app_client.get("/me").status_code == 401


def test_portal_user_resolves_team_from_team_id(app_client: TestClient, seeded):
    app_client.post("/login/parent", params={"team_code": "SNAP26"})
    body = app_client.get("/me").json()
    assert body["username"] == "parent"
    assert body["team_code"] == "SNAP26"
    assert body["team_ids"] == [seeded["team_id"]]


def test_portal_user_resolves_team_from_team_code_only(app_client: TestClient):
    # No team_id in the session — resolution must fall back to team_code.
    app_client.post("/login-code-only/parent", params={"team_code": "SNAP26"})
    assert app_client.get("/me").json()["team_code"] == "SNAP26"


def test_portal_user_without_selected_team(app_client: TestClient):
    app_client.post("/login/parent")
    body = app_client.get("/me").json()
    assert body["team_code"] is None


def test_portal_user_rejects_member_of_other_team(app_client: TestClient):
    app_client.post("/login/parent", params={"team_code": "HRBR1"})
    res = app_client.get("/me")
    assert res.status_code == 403
    assert res.json()["detail"] == "Not a member of this team"


def test_portal_user_rejects_user_without_membership(app_client: TestClient):
    app_client.post("/login/loner")
    res = app_client.get("/me")
    assert res.status_code == 403
    assert res.json()["detail"] == "No team membership"


def test_admin_without_membership_is_allowed(app_client: TestClient):
    app_client.post("/login/admin", params={"team_code": "HRBR1"})
    body = app_client.get("/me").json()
    assert body["username"] == "admin"
    assert body["team_code"] == "HRBR1"


def test_stale_session_user_is_logged_out(app_client: TestClient):
    app_client.post("/login-stale")
    assert app_client.get("/me").status_code == 401
    # Session was cleared, so a second call is still unauthenticated.
    assert app_client.get("/me").status_code == 401


def test_logout_clears_session(app_client: TestClient):
    app_client.post("/login/parent", params={"team_code": "SNAP26"})
    assert app_client.get("/me").status_code == 200
    app_client.post("/logout")
    assert app_client.get("/me").status_code == 401


def test_verify_user_password(fresh_db, seeded):
    with fresh_db.session_scope() as db:
        assert verify_user_password(db, "parent", "parent") is not None
        assert verify_user_password(db, "parent", "wrong") is None
        assert verify_user_password(db, "ghost", "parent") is None
