from __future__ import annotations

import pytest

from soccersnap.models import Team


@pytest.fixture()
def dbmod(isolated_settings):
    from soccersnap import db as module

    engine, session_local = module._engine, module.SessionLocal
    module._engine = None
    module.SessionLocal = None
    yield module
    module._engine = engine
    module.SessionLocal = session_local


def test_get_engine_prepares_data_dir_for_relative_sqlite(dbmod, isolated_settings, monkeypatch):
    monkeypatch.chdir(isolated_settings.data_dir.parent)
    dbmod.get_engine("sqlite:///./data/soccersnap.db")
    assert isolated_settings.data_dir.is_dir()


def test_session_scope_commits(dbmod, isolated_settings):
    dbmod.init_db(isolated_settings.database_url)
    with dbmod.session_scope() as db:
        db.add(Team(name="SoccerSnap FC", team_code="SNAP26"))
    with dbmod.session_scope() as db:
        assert db.query(Team).one().team_code == "SNAP26"


def test_session_scope_rolls_back_on_error(dbmod, isolated_settings):
    dbmod.init_db(isolated_settings.database_url)
    with pytest.raises(RuntimeError):
        with dbmod.session_scope() as db:
            db.add(Team(name="Ghost FC", team_code="GHOST"))
            raise RuntimeError("boom")
    with dbmod.session_scope() as db:
        assert db.query(Team).count() == 0


def test_session_scope_initializes_lazily(dbmod, isolated_settings):
    assert dbmod.SessionLocal is None
    with dbmod.session_scope() as db:
        assert db.query(Team).count() == 0
    assert dbmod.SessionLocal is not None


def test_get_session_initializes_lazily_and_rolls_back(dbmod, isolated_settings):
    assert dbmod.SessionLocal is None
    generator = dbmod.get_session()
    db = next(generator)
    db.add(Team(name="Ghost FC", team_code="GHOST"))
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("boom"))

    with dbmod.session_scope() as fresh:
        assert fresh.query(Team).count() == 0
