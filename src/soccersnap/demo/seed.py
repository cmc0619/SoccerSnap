from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from soccersnap.config import settings
from soccersnap.models import Membership, Team, User
from soccersnap.portal.auth import hash_password


def seed_demo(db: Session) -> dict:
    team = db.query(Team).filter_by(team_code=settings.demo_team_code).one_or_none()
    if team is None:
        team = Team(
            name="SoccerSnap FC",
            team_code=settings.demo_team_code,
            season="2026",
            age_group="U12",
        )
        db.add(team)
        db.flush()

    admin = db.query(User).filter_by(username=settings.admin_user).one_or_none()
    if admin is None:
        admin = User(
            username=settings.admin_user,
            password_hash=hash_password(settings.admin_password),
            role="admin",
            display_name="Admin",
        )
        db.add(admin)
        db.flush()
        db.add(Membership(user_id=admin.id, team_id=team.id, role="admin", jersey_number=None))

    if not settings.demo_mode:
        # Known-password watcher accounts exist for the demo only.
        db.flush()
        return {
            "team_code": team.team_code,
            "team_name": team.name,
            "admin_user": settings.admin_user,
            "watchers": [],
        }

    coach = db.query(User).filter_by(username="coach").one_or_none()
    if coach is None:
        coach = User(
            username="coach",
            password_hash=hash_password("coach"),
            role="coach",
            display_name="Coach Avery",
        )
        db.add(coach)
        db.flush()
        db.add(Membership(user_id=coach.id, team_id=team.id, role="coach"))

    parent = db.query(User).filter_by(username="parent").one_or_none()
    if parent is None:
        parent = User(
            username="parent",
            password_hash=hash_password("parent"),
            role="parent",
            display_name="Alex Parent",
        )
        db.add(parent)
        db.flush()
        db.add(Membership(user_id=parent.id, team_id=team.id, role="parent", jersey_number=9))

    db.flush()
    return {
        "team_code": team.team_code,
        "team_name": team.name,
        "admin_user": settings.admin_user,
        "watchers": ["coach/coach", "parent/parent"],
        "kickoff_hint": (datetime.utcnow() + timedelta(days=1)).isoformat(),
    }
