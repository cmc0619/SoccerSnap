"""Auth helpers: ops API key for rig/process; signed session for portal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from soccersnap.config import settings
from soccersnap.db import get_session
from soccersnap.models import Game, Membership, Team, User
from soccersnap.portal.auth import verify_password

basic_security = HTTPBasic(auto_error=False)


def _ops_key_valid(provided: str | None) -> bool:
    return bool(provided) and provided == settings.ops_api_key


def admin_credentials_valid(credentials: HTTPBasicCredentials | None) -> bool:
    return (
        credentials is not None
        and credentials.username == settings.admin_user
        and credentials.password == settings.admin_password
    )


def basic_auth_required(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def require_ops(
    x_soccersnap_key: Annotated[str | None, Header(alias="X-SoccerSnap-Key")] = None,
    credentials: HTTPBasicCredentials | None = Depends(basic_security),
) -> None:
    """Protect destructive/offload endpoints (confirm, cleanup, upload, process)."""
    if _ops_key_valid(x_soccersnap_key):
        return
    if admin_credentials_valid(credentials):
        return
    if credentials is not None and credentials.password == settings.ops_api_key:
        return
    raise basic_auth_required("Ops authentication required")


@dataclass
class PortalPrincipal:
    user: User
    team: Team | None
    team_ids: list[int]


def login_session(request: Request, user: User, team: Team | None) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role
    request.session["team_code"] = team.team_code if team else None
    request.session["team_id"] = team.id if team else None


def logout_session(request: Request) -> None:
    request.session.clear()


def require_portal_user(
    request: Request,
    db: Session = Depends(get_session),
) -> PortalPrincipal:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if not user:
        logout_session(request)
        raise HTTPException(status_code=401, detail="Login required")

    memberships = db.query(Membership).filter_by(user_id=user.id).all()
    team_ids = [m.team_id for m in memberships]
    team = None
    team_id = request.session.get("team_id")
    team_code = request.session.get("team_code")
    if team_id:
        team = db.query(Team).filter_by(id=team_id).one_or_none()
    elif team_code:
        team = db.query(Team).filter_by(team_code=team_code).one_or_none()

    if user.role != "admin":
        if not team_ids:
            raise HTTPException(status_code=403, detail="No team membership")
        if team and team.id not in team_ids:
            raise HTTPException(status_code=403, detail="Not a member of this team")

    return PortalPrincipal(user=user, team=team, team_ids=team_ids)


def assert_game_access(principal: PortalPrincipal, game: Game) -> None:
    """Allow any team the user belongs to; selected team is a UI filter, not a hard ACL."""
    if principal.user.role == "admin":
        return
    if game.team_id not in principal.team_ids:
        raise HTTPException(status_code=403, detail="Forbidden for this team")


def verify_user_password(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None
