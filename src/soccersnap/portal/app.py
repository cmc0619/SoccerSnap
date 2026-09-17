from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from soccersnap.db import get_session
from soccersnap.models import Clip, Game, GameEvent, Membership, Team, User
from soccersnap.portal import serializers
from soccersnap.portal.auth import verify_password
from soccersnap.protocol.query import parse_query, search_events
from soccersnap.security import (
    PortalPrincipal,
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
        return serializers.team_dict(row)

    @router.get("/games")
    def games(
        team_code: str | None = None,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        q = serializers.scope_to_teams(db.query(Game).order_by(Game.kickoff.desc()), principal)
        code = team_code or (principal.team.team_code if principal.team else None)
        if code:
            team = db.query(Team).filter_by(team_code=code).one_or_none()
            if not team:
                return {"games": []}
            if principal.user.role != "admin" and team.id not in principal.team_ids:
                raise HTTPException(status_code=403, detail="Forbidden")
            q = q.filter(Game.team_id == team.id)
        return {"games": [serializers.game_summary(g) for g in q.all()]}

    @router.get("/games/{game_id}")
    def game_detail(
        game_id: int,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        return serializers.game_detail(serializers.game_for_principal(db, game_id, principal))

    def _search_impl(q: str, game_id: int | None, principal: PortalPrincipal, db: Session):
        parsed = parse_query(q)
        query = serializers.scope_to_teams(
            db.query(GameEvent).join(Game, GameEvent.game_id == Game.id), principal
        )
        if game_id is not None:
            serializers.game_for_principal(db, game_id, principal)
            query = query.filter(GameEvent.game_id == game_id)
        events = [serializers.event_dict(e) for e in query.all()]
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
        serializers.game_for_principal(db, body.game_id, principal)
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
        return serializers.clip_dict(clip)

    @router.get("/clips")
    def list_clips(
        game_id: int | None = None,
        principal: PortalPrincipal = Depends(require_portal_user),
        db: Session = Depends(get_session),
    ):
        q = serializers.scope_to_teams(
            db.query(Clip).join(Game, Clip.game_id == Game.id).order_by(Clip.id.desc()), principal
        )
        if game_id is not None:
            serializers.game_for_principal(db, game_id, principal)
            q = q.filter(Clip.game_id == game_id)
        return {"clips": [serializers.clip_dict(c) for c in q.all()]}

    return router
