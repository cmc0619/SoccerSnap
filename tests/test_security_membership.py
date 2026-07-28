from __future__ import annotations

import pytest
from fastapi import HTTPException

from soccersnap.models import Game, Team, User
from soccersnap.security import PortalPrincipal, assert_game_access


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
