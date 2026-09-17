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

    members = (
        (settings.admin_user, settings.admin_password, "admin", "Admin", None),
        ("coach", "coach", "coach", "Coach Avery", None),
        ("parent", "parent", "parent", "Alex Parent", 9),
    )
    for username, password, role, display_name, jersey_number in members:
        if db.query(User).filter_by(username=username).one_or_none() is not None:
            continue
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            display_name=display_name,
        )
        db.add(user)
        db.flush()
        db.add(
            Membership(
                user_id=user.id,
                team_id=team.id,
                role=role,
                jersey_number=jersey_number,
            )
        )

    db.flush()
    return {
        "team_code": team.team_code,
        "team_name": team.name,
        "admin_user": settings.admin_user,
        "watchers": ["coach/coach", "parent/parent"],
        "kickoff_hint": (datetime.utcnow() + timedelta(days=1)).isoformat(),
    }
