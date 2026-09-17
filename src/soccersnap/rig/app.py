from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from soccersnap.config import settings
from soccersnap.media import FFmpegError
from soccersnap.protocol.ids import InvalidIdError, validate_camera_id, validate_session_id
from soccersnap.protocol.schemas import (
    ConfirmRequest,
    CoordinatorStartRequest,
    StartRecordingRequest,
)
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.rig.framing import assess_framing
from soccersnap.rig.recorder import RecorderError
from soccersnap.security import require_ops


def create_rig_router(coordinator: FleetCoordinator | None = None) -> APIRouter:
    coord = coordinator or FleetCoordinator()
    router = APIRouter(prefix="/api/v1", tags=["rig"])

    @router.get("/health")
    def health():
        disk = coord.fleet.disk_status()
        return {
            "status": "healthy",
            "storage_free_gb": disk.free_gb,
            "active_uploads": 0,
            "version": settings.software_version,
        }

    @router.get("/status")
    def status():
        return coord.aggregated_status()

    @router.get("/coordinator/status")
    def coordinator_status():
        return coord.aggregated_status()

    @router.get("/coordinator/peers")
    def coordinator_peers():
        return {"peers": coord.peers()}

    @router.post("/coordinator/preflight")
    def coordinator_preflight():
        return coord.preflight()

    @router.post("/coordinator/start", dependencies=[Depends(require_ops)])
    def coordinator_start(body: CoordinatorStartRequest | None = None):
        req = body or CoordinatorStartRequest()
        try:
            if req.session_id:
                validate_session_id(req.session_id)
        except InvalidIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = coord.start_all(req.session_id, delay_sec=req.delay_sec)
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result)
        return result

    @router.post("/coordinator/stop", dependencies=[Depends(require_ops)])
    def coordinator_stop(duration_sec: float | None = None):
        try:
            return coord.stop_all(duration_sec=duration_sec)
        except (FFmpegError, RecorderError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/record/start", dependencies=[Depends(require_ops)])
    def record_start(body: StartRecordingRequest | None = None):
        req = body or StartRecordingRequest()
        try:
            if req.session_id:
                validate_session_id(req.session_id)
        except InvalidIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Honor absolute scheduled_start when provided by coordinator broadcast.
        if req.scheduled_start is not None:
            from datetime import datetime, timezone
            import time as time_mod

            target = req.scheduled_start
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            wait = (target - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                time_mod.sleep(wait)
            result = coord.start_all(req.session_id, delay_sec=0.0)
        else:
            result = coord.start_all(req.session_id, delay_sec=0.05)
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result)
        return result

    @router.post("/record/stop", dependencies=[Depends(require_ops)])
    def record_stop():
        try:
            return coord.stop_all()
        except (FFmpegError, RecorderError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/recordings", dependencies=[Depends(require_ops)])
    def recordings():
        # Checksums enable confirm/delete — ops auth required.
        return {"recordings": coord.fleet.recordings()}

    @router.post("/recordings/confirm", dependencies=[Depends(require_ops)])
    def recordings_confirm(body: ConfirmRequest):
        try:
            marked = coord.fleet.confirm(body)
            return {"success": True, "manifest": marked.flat(), "offloaded": marked.offloaded}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/recordings/cleanup", dependencies=[Depends(require_ops)])
    def recordings_cleanup():
        result = coord.fleet.cleanup_offloaded()
        if result["failed"]:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Some offloaded recordings could not be deleted",
                    **result,
                },
            )
        return result

    @router.get("/framing/{camera_id}")
    def framing(camera_id: str):
        result = assess_framing(camera_id, simulate=coord.fleet.simulate)
        return {
            "camera_id": camera_id,
            "quality": result.quality.value,
            "score": result.score,
            "message": result.message,
            "tone_hz": result.tone_hz,
        }

    @router.get("/recordings/{session_id}/{camera_id}/media", dependencies=[Depends(require_ops)])
    def recording_media(session_id: str, camera_id: str):
        try:
            session_id = validate_session_id(session_id)
            camera_id = validate_camera_id(camera_id)
        except InvalidIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        path = settings.recordings_dir / f"{session_id}_{camera_id}.mp4"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Media not found")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    return router


def create_rig_app(coordinator: FleetCoordinator | None = None) -> FastAPI:
    app = FastAPI(title="SoccerSnap Rig", version=settings.software_version)
    app.include_router(create_rig_router(coordinator))
    return app
