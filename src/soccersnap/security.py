"""Auth helpers: ops API key for rig/process; signed session for portal."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from hmac import compare_digest
from threading import Lock
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from soccersnap.config import settings
from soccersnap.db import get_session
from soccersnap.models import Game, Membership, Team, User
from soccersnap.portal.auth import verify_password

basic_security = HTTPBasic(auto_error=False)


def _secret_matches(provided: str | None, configured: str) -> bool:
    """Constant-time compare that never authenticates against an unset secret."""
    if not provided or not configured:
        return False
    return compare_digest(provided, configured)


def _ops_key_valid(provided: str | None) -> bool:
    return _secret_matches(provided, settings.ops_api_key)


_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_ATTEMPTS_GUARD = Lock()


def enforce_rate_limit(key: str, *, limit: int = 10, window_sec: float = 60.0) -> None:
    """Throttle credential-guessing against login/unlock endpoints."""
    now = time.monotonic()
    with _ATTEMPTS_GUARD:
        hits = _ATTEMPTS[key]
        while hits and now - hits[0] > window_sec:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = int(window_sec - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many attempts — try again later",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)


def client_key(request: Request, suffix: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{suffix}"


def admin_credentials_valid(credentials: HTTPBasicCredentials | None) -> bool:
    if credentials is None:
        return False
    user_ok = _secret_matches(credentials.username, settings.admin_user)
    password_ok = _secret_matches(credentials.password, settings.admin_password)
    return user_ok and password_ok


def require_ops(
    x_soccersnap_key: Annotated[str | None, Header(alias="X-SoccerSnap-Key")] = None,
    credentials: HTTPBasicCredentials | None = Depends(basic_security),
) -> None:
    """Protect destructive/offload endpoints (confirm, cleanup, upload, process)."""
    if _ops_key_valid(x_soccersnap_key):
        return
    if admin_credentials_valid(credentials):
        return
    if credentials is not None and _ops_key_valid(credentials.password):
        return
    raise HTTPException(
        status_code=401,
        detail="Ops authentication required",
        headers={"WWW-Authenticate": "Basic"},
    )


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
