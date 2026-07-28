from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="parent")  # admin|coach|parent
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    team_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    season: Mapped[str] = mapped_column(String(32), default="2026")
    age_group: Mapped[str] = mapped_column(String(32), default="U12")

    memberships: Mapped[list["Membership"]] = relationship(back_populates="team")
    games: Mapped[list["Game"]] = relationship(back_populates="team")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "team_id", name="uq_user_team"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="parent")

    user: Mapped[User] = relationship(back_populates="memberships")
    team: Mapped[Team] = relationship(back_populates="memberships")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    opponent: Mapped[str] = mapped_column(String(120), default="Opponent")
    location: Mapped[str] = mapped_column(String(120), default="Home Field")
    is_home: Mapped[bool] = mapped_column(Boolean, default=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    # scheduled | recording | processing | ready
    video_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")

    team: Mapped[Team] = relationship(back_populates="games")
    events: Mapped[list["GameEvent"]] = relationship(back_populates="game", cascade="all, delete-orphan")
    assets: Mapped[list["CameraAsset"]] = relationship(back_populates="game", cascade="all, delete-orphan")
    clips: Mapped[list["Clip"]] = relationship(back_populates="game", cascade="all, delete-orphan")


class CameraAsset(Base):
    __tablename__ = "camera_assets"
    __table_args__ = (UniqueConstraint("session_id", "camera_id", name="uq_session_cam"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[Optional[int]] = mapped_column(ForeignKey("games.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    camera_id: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(128), default="")
    offset_ms: Mapped[float] = mapped_column(Float, default=0.0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    path: Mapped[str] = mapped_column(String(512))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    game: Mapped[Optional[Game]] = relationship(back_populates="assets")


class GameEvent(Base):
    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    t_start_ms: Mapped[int] = mapped_column(Integer, default=0)
    t_end_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    game: Mapped[Game] = relationship(back_populates="events")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="Clip")
    t_start_ms: Mapped[int] = mapped_column(Integer, default=0)
    t_end_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(64), default="viewer")

    game: Mapped[Game] = relationship(back_populates="clips")
