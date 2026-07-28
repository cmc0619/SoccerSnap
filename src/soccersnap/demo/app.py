from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from soccersnap import __version__
from soccersnap.config import settings
from soccersnap.db import init_db, session_scope
from soccersnap.demo.seed import seed_demo
from soccersnap.portal.app import create_portal_router
from soccersnap.process.app import create_process_router
from soccersnap.process.pipeline import ProcessPipeline
from soccersnap.rig.app import create_rig_router
from soccersnap.rig.coordinator import FleetCoordinator


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def create_demo_app() -> FastAPI:
    settings.ensure_dirs()
    init_db()
    with session_scope() as db:
        seed_info = seed_demo(db)

    coordinator = FleetCoordinator()
    pipeline = ProcessPipeline(
        sessions_dir=settings.staging_dir / "sessions",
        media_dir=settings.media_dir,
        recordings_dir=settings.recordings_dir,
    )

    app = FastAPI(
        title="SoccerSnap",
        version=__version__,
        description="Synchronized multi-camera soccer capture → process → watch",
    )
    app.state.coordinator = coordinator
    app.state.pipeline = pipeline
    app.state.seed = seed_info

    app.include_router(create_rig_router(coordinator))
    app.include_router(create_process_router(pipeline, coordinator))
    app.include_router(create_portal_router())

    @app.get("/api/demo/info")
    def demo_info():
        return {
            "product": "SoccerSnap",
            "version": __version__,
            "seed": seed_info,
            "endpoints": {
                "field": "/field/",
                "watch": "/watch/",
                "docs": "/docs",
            },
        }

    @app.post("/api/demo/run-match")
    def run_match(delay_sec: float = 0.05, duration_sec: float = 4.0, opponent: str = "Rivals"):
        """One-shot: scheduled start → stop → PROTOCOL ingest/process → ready game."""
        from soccersnap.db import SessionLocal

        start = coordinator.start_all(delay_sec=delay_sec)
        if not start.get("success"):
            raise HTTPException(status_code=409, detail=start)
        stop = coordinator.stop_all(duration_sec=duration_sec)
        session_id = stop["session_id"]
        assert SessionLocal is not None
        db = SessionLocal()
        try:
            processed = pipeline.process_session(session_id, db=db, opponent=opponent)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {"start": start, "stop": stop, "processed": processed}

    media_dir = settings.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/media/{name}")
    def media(name: str):
        path = media_dir / name
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, media_type="video/mp4" if name.endswith(".mp4") else "application/octet-stream")

    if (WEB_ROOT / "field").exists():
        app.mount("/field", StaticFiles(directory=str(WEB_ROOT / "field"), html=True), name="field")
    if (WEB_ROOT / "watch").exists():
        app.mount("/watch", StaticFiles(directory=str(WEB_ROOT / "watch"), html=True), name="watch")

    @app.get("/")
    def root():
        return FileResponse(WEB_ROOT / "index.html") if (WEB_ROOT / "index.html").exists() else {
            "product": "SoccerSnap",
            "field": "/field/",
            "watch": "/watch/",
        }

    return app
