"""Single source of truth for the JSON shapes the watch portal returns."""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from soccersnap.models import Clip, Game, GameEvent, Team
from soccersnap.security import PortalPrincipal, assert_game_access


def team_dict(team: Team) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "team_code": team.team_code,
        "season": team.season,
        "age_group": team.age_group,
    }


def event_dict(event: GameEvent) -> dict:
    return {
        "id": event.id,
        "game_id": event.game_id,
        "type": event.type,
        "t_start_ms": event.t_start_ms,
        "t_end_ms": event.t_end_ms,
        "confidence": event.confidence,
        "jersey_number": event.jersey_number,
        "label": event.label,
        "payload": json.loads(event.payload_json or "{}"),
    }


def game_summary(game: Game) -> dict:
    return {
        "id": game.id,
        "session_id": game.session_id,
        "opponent": game.opponent,
        "location": game.location,
        "is_home": game.is_home,
        "kickoff": game.kickoff.isoformat(),
        "status": game.status,
        "video_path": game.video_path,
        "duration_sec": game.duration_sec,
        "event_count": len(game.events),
    }


def game_detail(game: Game) -> dict:
    return {
        **game_summary(game),
        "events": [event_dict(e) for e in sorted(game.events, key=lambda x: x.t_start_ms)],
    }


def clip_dict(clip: Clip) -> dict:
    return {
        "id": clip.id,
        "game_id": clip.game_id,
        "title": clip.title,
        "t_start_ms": clip.t_start_ms,
        "t_end_ms": clip.t_end_ms,
        "created_by": clip.created_by,
    }


def scope_to_teams(query: Query, principal: PortalPrincipal) -> Query:
    """Restrict a Game-joined query to the principal's teams (admins see all)."""
    if principal.user.role == "admin":
        return query
    return query.filter(Game.team_id.in_(principal.team_ids or [-1]))


def game_for_principal(db: Session, game_id: int, principal: PortalPrincipal) -> Game:
    game = db.query(Game).filter_by(id=game_id).one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    assert_game_access(principal, game)
    return game
