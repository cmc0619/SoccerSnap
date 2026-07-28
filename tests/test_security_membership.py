from __future__ import annotations

import pytest
from fastapi import HTTPException

from soccersnap.config import Settings
from soccersnap.models import Game, Team, User
from soccersnap.security import PortalPrincipal, assert_game_access


def blank_settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        secret_key="",
        ops_api_key="",
        admin_password="",
        **overrides,
    )


def test_non_demo_refuses_unset_secrets():
    config = blank_settings(demo_mode=False)
    assert config.ensure_demo_secrets() == {}
    with pytest.raises(RuntimeError):
        config.validate_runtime_secrets()


def test_demo_mode_generates_unique_secrets():
    first = blank_settings(demo_mode=True)
    second = blank_settings(demo_mode=True)
    first.ensure_demo_secrets()
    second.ensure_demo_secrets()
    assert first.secret_key and first.ops_api_key and first.admin_password
    assert first.secret_key != second.secret_key
    assert first.ops_api_key != second.ops_api_key


def test_assert_game_access_allows_any_membership():
    user = User(id=1, username="parent", password_hash="x", role="parent")
    team_a = Team(id=10, name="A", team_code="AAAA")
    principal = PortalPrincipal(user=user, team=team_a, team_ids=[10, 11])
    other_team_game = Game(id=5, session_id="G1", team_id=11, opponent="X")

    # Selected team A, game belongs to membership team B — must be allowed.
    assert_game_access(principal, other_team_game)

    outsider = Game(id=6, session_id="G2", team_id=99, opponent="Y")
    with pytest.raises(HTTPException) as exc:
        assert_game_access(principal, outsider)
    assert exc.value.status_code == 403
