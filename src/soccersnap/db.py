from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from soccersnap.config import settings
from soccersnap.models import Base

_engine = None
SessionLocal: sessionmaker[Session] | None = None


def get_engine(url: str | None = None):
    global _engine, SessionLocal
    db_url = url or settings.database_url
    if db_url.startswith("sqlite:///./"):
        settings.ensure_dirs()
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db(url: str | None = None) -> None:
    engine = get_engine(url)
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """Commit-on-success session, used both as a FastAPI dependency and directly."""
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


session_scope = contextmanager(get_session)
