from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from soccersnap.db import get_session
from soccersnap.models import Clip, Game, GameEvent, Membership, Team, User
from soccersnap.portal.auth import verify_password
from soccersnap.protocol.query import parse_query, search_events
from soccersnap.security import (
    PortalPrincipal,
    assert_game_access,
    login_session,
    logout_session,
    require_portal_user,
)


class LoginBody(BaseModel):
    username: str
    password: str
    team_code: str | None = None


class ClipCreate(BaseModel):
    game_id: int
    title: str = "Clip"
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(ge=0)


class SearchBody(BaseModel):
    q: str
    game_id: int | None = None


def create_portal_router() -> APIRouter:
    router = APIRouter(prefix="/api/portal", tags=["portal"])

    @router.post("/login")
    def login(body: LoginBody, request: Request, db: Session = Depends(get_session)):
        user = db.query(User).filter_by(username=body.username).one_or_none()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        team = None
        if body.team_code:
            team = db.query(Team).filter_by(team_code=body.team_code).one_or_none()
            if team is None:
                raise HTTPException(status_code=404, detail="Unknown team code")
            if user.role != "admin":
                membership = (
                    db.query(Membership)
                    .filter_by(user_id=user.id, team_id=team.id)
                    .one_or_none()
                )
                if membership is None:
                    raise HTTPException(status_code=403, detail="Not a member of this team")
        elif user.role != "admin":
            membership = db.query(Membership).filter_by(user_id=user.id).first()
            if membership:
                team = db.query(Team).filter_by(id=membership.team_id).one()
        login_session(request, user, team)
        return {
            "ok": True,
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "team_code": team.team_code if team else None,
        }

    @router.post("/logout")
    def logout(request: Request):
        logout_session(request)
        return {"ok": True}

    @router.get("/me")
    def me(principal: PortalPrincipal = Depends(require_portal_user)):
        return {
            "username": principal.user.username,
            "role": principal.user.role,
            "display_name": principal.user.display_name,
            "team_code": principal.team.team_code if principal.team else None,
        }

    @router.get("/teams/{team_code}")
    def team(
        team_code: str,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        row = db.query(Team).filter_by(team_code=team_code).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Team not found")
        if principal.user.role != "admin" and row.id not in principal.team_ids:
            raise HTTPException(status_code=403, detail="Forbidden")
        return {
            "id": row.id,
            "name": row.name,
            "team_code": row.team_code,
            "season": row.season,
            "age_group": row.age_group,
        }

    @router.get("/games")
    def games(
        team_code: str | None = None,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        q = db.query(Game).order_by(Game.kickoff.desc())
        if principal.user.role != "admin":
            q = q.filter(Game.team_id.in_(principal.team_ids or [-1]))
        code = team_code or (principal.team.team_code if principal.team else None)
        if code:
            team = db.query(Team).filter_by(team_code=code).one_or_none()
            if not team:
                return {"games": []}
            if principal.user.role != "admin" and team.id not in principal.team_ids:
                raise HTTPException(status_code=403, detail="Forbidden")
            q = q.filter(Game.team_id == team.id)
        rows = q.all()
        return {
            "games": [
                {
                    "id": g.id,
                    "session_id": g.session_id,
                    "opponent": g.opponent,
                    "location": g.location,
                    "is_home": g.is_home,
                    "kickoff": g.kickoff.isoformat(),
                    "status": g.status,
                    "video_path": g.video_path,
                    "duration_sec": g.duration_sec,
                    "event_count": len(g.events),
                }
                for g in rows
            ]
        }

    @router.get("/games/{game_id}")
    def game_detail(
        game_id: int,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        g = db.query(Game).filter_by(id=game_id).one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="Game not found")
        assert_game_access(principal, g)
        events = [
            {
                "id": e.id,
                "type": e.type,
                "t_start_ms": e.t_start_ms,
                "t_end_ms": e.t_end_ms,
                "confidence": e.confidence,
                "jersey_number": e.jersey_number,
                "label": e.label,
                "payload": json.loads(e.payload_json or "{}"),
            }
            for e in sorted(g.events, key=lambda x: x.t_start_ms)
        ]
        return {
            "id": g.id,
            "session_id": g.session_id,
            "opponent": g.opponent,
            "location": g.location,
            "status": g.status,
            "video_path": g.video_path,
            "duration_sec": g.duration_sec,
            "kickoff": g.kickoff.isoformat(),
            "events": events,
        }

    def _search_impl(q: str, game_id: int | None, principal: PortalPrincipal, db: Session):
        parsed = parse_query(q)
        query = db.query(GameEvent).join(Game, GameEvent.game_id == Game.id)
        if principal.user.role != "admin":
            query = query.filter(Game.team_id.in_(principal.team_ids or [-1]))
        if game_id is not None:
            game = db.query(Game).filter_by(id=game_id).one_or_none()
            if not game:
                raise HTTPException(status_code=404, detail="Game not found")
            assert_game_access(principal, game)
            query = query.filter(GameEvent.game_id == game_id)
        events = [
            {
                "id": e.id,
                "game_id": e.game_id,
                "type": e.type,
                "t_start_ms": e.t_start_ms,
                "t_end_ms": e.t_end_ms,
                "jersey_number": e.jersey_number,
                "label": e.label,
                "payload": json.loads(e.payload_json or "{}"),
            }
            for e in query.all()
        ]
        hits = search_events(events, parsed)
        return {"query": parsed.__dict__, "results": hits}

    @router.get("/search")
    def search(
        q: str,
        game_id: int | None = None,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        return _search_impl(q, game_id, principal, db)

    @router.post("/search")
    def search_post(
        body: SearchBody,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        return _search_impl(body.q, body.game_id, principal, db)

    @router.post("/clips")
    def create_clip(
        body: ClipCreate,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        game = db.query(Game).filter_by(id=body.game_id).one_or_none()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        assert_game_access(principal, game)
        if body.t_end_ms < body.t_start_ms:
            raise HTTPException(status_code=400, detail="t_end_ms must be >= t_start_ms")
        clip = Clip(
            game_id=body.game_id,
            title=body.title,
            t_start_ms=body.t_start_ms,
            t_end_ms=body.t_end_ms,
            created_by=principal.user.username,
        )
        db.add(clip)
        db.flush()
        return {
            "id": clip.id,
            "game_id": clip.game_id,
            "title": clip.title,
            "t_start_ms": clip.t_start_ms,
            "t_end_ms": clip.t_end_ms,
        }

    @router.get("/clips")
    def list_clips(
        game_id: int | None = None,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        q = db.query(Clip).join(Game, Clip.game_id == Game.id).order_by(Clip.id.desc())
        if principal.user.role != "admin":
            q = q.filter(Game.team_id.in_(principal.team_ids or [-1]))
        if game_id is not None:
            game = db.query(Game).filter_by(id=game_id).one_or_none()
            if not game:
                raise HTTPException(status_code=404, detail="Game not found")
            assert_game_access(principal, game)
            q = q.filter(Clip.game_id == game_id)
        return {
            "clips": [
                {
                    "id": c.id,
                    "game_id": c.game_id,
                    "title": c.title,
                    "t_start_ms": c.t_start_ms,
                    "t_end_ms": c.t_end_ms,
                    "created_by": c.created_by,
                }
                for c in q.all()
            ]
        }

    return router
