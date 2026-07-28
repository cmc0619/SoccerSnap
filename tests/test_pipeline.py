from __future__ import annotations

import json
from pathlib import Path

import pytest

from soccersnap.models import CameraAsset, Game, Team
from soccersnap.process import pipeline as pipeline_mod
from soccersnap.process.pipeline import ProcessPipeline
from soccersnap.process.stitcher import stitch_hstack
from soccersnap.protocol.manifests import load_manifest
from soccersnap.protocol.offload import OffloadError
from soccersnap.rig.recorder import RecorderFleet


@pytest.fixture()
def stub_stitch(monkeypatch: pytest.MonkeyPatch):
    def _stitch(camera_paths: list[Path], output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"stitched:" + b",".join(p.name.encode() for p in camera_paths))
        return output

    monkeypatch.setattr(pipeline_mod, "stitch_hstack", _stitch)


@pytest.fixture()
def pipeline(isolated_settings, fake_clips) -> ProcessPipeline:
    return ProcessPipeline(
        sessions_dir=isolated_settings.staging_dir / "sessions",
        media_dir=isolated_settings.media_dir,
        recordings_dir=isolated_settings.recordings_dir,
    )


@pytest.fixture()
def recorded(pipeline: ProcessPipeline):
    fleet = RecorderFleet(base_dir=pipeline.recordings_dir, simulate=True)
    fleet.start("GAME_PIPE_001")
    fleet.stop(duration_sec=4.0)
    return "GAME_PIPE_001"


def test_health_and_empty_session_listing(pipeline: ProcessPipeline):
    health = pipeline.health()
    assert health["status"] == "healthy"
    assert health["storage_free_gb"] > 0
    assert pipeline.list_ready_sessions() == []


def test_list_ready_sessions_missing_dir(isolated_settings):
    pipeline = ProcessPipeline(
        sessions_dir=isolated_settings.staging_dir / "sessions",
        media_dir=isolated_settings.media_dir,
        recordings_dir=isolated_settings.recordings_dir,
    )
    pipeline.sessions_dir.rmdir()
    assert pipeline.list_ready_sessions() == []


def test_ingest_missing_manifest_raises(pipeline: ProcessPipeline):
    with pytest.raises(FileNotFoundError, match="Manifest missing"):
        pipeline.ingest_from_rig("GAME_ABSENT", "CAM_L")


def test_ingest_rejects_traversal_in_manifest_file_name(pipeline: ProcessPipeline, recorded: str):
    manifest_path = pipeline.recordings_dir / f"{recorded}_CAM_L.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["file"]["name"] = "../escape.mp4"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(OffloadError, match="Invalid media file name"):
        pipeline.ingest_from_rig(recorded, "CAM_L")


def test_ingest_missing_media_raises(pipeline: ProcessPipeline, recorded: str):
    manifest = load_manifest(pipeline.recordings_dir / f"{recorded}_CAM_L.json")
    (pipeline.recordings_dir / manifest.file_name).unlink()
    with pytest.raises(FileNotFoundError, match="Media missing"):
        pipeline.ingest_from_rig(recorded, "CAM_L")


def test_ingest_detects_confirm_checksum_mismatch(pipeline: ProcessPipeline, recorded: str, monkeypatch):
    monkeypatch.setattr(
        pipeline_mod,
        "confirm_upload",
        lambda **_kwargs: {"checksum_sha256": "0" * 64},
    )
    with pytest.raises(OffloadError, match="Confirm checksum mismatch"):
        pipeline.ingest_from_rig(recorded, "CAM_L")


def test_ingest_session_requires_assets(pipeline: ProcessPipeline):
    with pytest.raises(FileNotFoundError, match="No camera assets"):
        pipeline.ingest_session("GAME_EMPTY")


def test_ingest_session_records_assets_and_advances_game(pipeline, recorded, fresh_db):
    with fresh_db.session_scope() as db:
        team = Team(name="SoccerSnap FC", team_code="SNAP26")
        db.add(team)
        db.flush()
        db.add(Game(session_id=recorded, team_id=team.id, opponent="Rivals", status="recording"))
        db.flush()

    with fresh_db.session_scope() as db:
        results = pipeline.ingest_session(recorded, db=db)
        assert len(results) == 3

    with fresh_db.session_scope() as db:
        assets = db.query(CameraAsset).filter_by(session_id=recorded).all()
        assert {a.camera_id for a in assets} == {"CAM_L", "CAM_C", "CAM_R"}
        assert all(a.confirmed and a.game_id for a in assets)
        assert db.query(Game).filter_by(session_id=recorded).one().status == "processing"

    # Re-ingesting updates the existing asset rows instead of duplicating them.
    with fresh_db.session_scope() as db:
        pipeline.ingest_session(recorded, db=db)
    with fresh_db.session_scope() as db:
        assert db.query(CameraAsset).filter_by(session_id=recorded).count() == 3


def test_process_session_creates_game_and_events(pipeline, recorded, fresh_db, stub_stitch):
    with fresh_db.session_scope() as db:
        result = pipeline.process_session(recorded, db=db, opponent="Harbor FC")

    assert result["status"] == "ready"
    assert result["ingested"] == 3
    assert result["events"] > 0
    assert result["video_path"] == f"/media/{recorded}_stitched.mp4"
    assert (pipeline.media_dir / f"{recorded}_stitched.mp4").exists()
    events = json.loads((pipeline.media_dir / f"{recorded}_events.json").read_text(encoding="utf-8"))
    assert len(events) == result["events"]

    with fresh_db.session_scope() as db:
        game = db.query(Game).filter_by(session_id=recorded).one()
        assert game.opponent == "Harbor FC"
        assert game.duration_sec == 4.0
        assert len(game.events) == result["events"]
        # Fallback team was created because no team existed.
        assert db.query(Team).one().team_code == "SNAP26"


def test_process_session_is_idempotent_on_events(pipeline, recorded, fresh_db, stub_stitch):
    with fresh_db.session_scope() as db:
        first = pipeline.process_session(recorded, db=db)
    with fresh_db.session_scope() as db:
        second = pipeline.process_session(recorded, db=db)
        game = db.query(Game).filter_by(session_id=recorded).one()
        assert len(game.events) == second["events"]
    assert first["game_id"] == second["game_id"]


def test_process_session_requires_three_cameras(pipeline, recorded, fresh_db):
    (pipeline.recordings_dir / f"{recorded}_CAM_R.json").unlink()
    with fresh_db.session_scope() as db:
        with pytest.raises(RuntimeError, match="CAM_L, CAM_C, and CAM_R"):
            pipeline.process_session(recorded, db=db)


def test_stitcher_requires_two_inputs(tmp_path: Path):
    with pytest.raises(ValueError, match="at least two camera clips"):
        stitch_hstack([tmp_path / "only.mp4"], tmp_path / "out.mp4")
