from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from soccersnap.config import settings
from soccersnap.db import get_session
from soccersnap.media import FFmpegError
from soccersnap.protocol.ids import InvalidIdError, validate_camera_id, validate_session_id
from soccersnap.protocol.manifests import SessionManifest
from soccersnap.protocol.offload import OffloadError, confirm_upload, store_upload
from soccersnap.protocol.schemas import UploadConfirmRequest
from soccersnap.process.pipeline import ProcessPipeline
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.security import require_ops

logger = logging.getLogger(__name__)


class ProcessRequest(BaseModel):
    session_id: str
    opponent: str = "Rivals"


def _http_ids(session_id: str | None = None, camera_id: str | None = None) -> tuple[str | None, str | None]:
    try:
        sid = validate_session_id(session_id) if session_id is not None else None
        cam = validate_camera_id(camera_id) if camera_id is not None else None
        return sid, cam
    except InvalidIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _stream_upload_to_temp(file: UploadFile, dest: Path, max_bytes: int) -> int:
    """Write upload in chunks; enforce size cap without buffering whole file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    chunk_size = 1024 * 1024
    with dest.open("wb") as handle:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds max size of {max_bytes} bytes",
                )
            handle.write(chunk)
    return written


def create_process_router(
    pipeline: ProcessPipeline | None = None,
    coordinator: FleetCoordinator | None = None,
) -> APIRouter:
    settings.ensure_dirs()
    pipe = pipeline or ProcessPipeline(
        sessions_dir=settings.staging_dir / "sessions",
        media_dir=settings.media_dir,
        recordings_dir=settings.recordings_dir,
    )
    coord = coordinator
    router = APIRouter(prefix="/api/v1", tags=["process"])

    @router.get("/health")
    def health():
        return pipe.health()

    @router.post("/upload", dependencies=[Depends(require_ops)])
    async def upload(
        file: UploadFile = File(...),
        session_id: str = Form(...),
        camera_id: str = Form(...),
        checksum: str = Form(...),
        manifest: str | None = Form(None),
    ):
        settings.ensure_dirs()
        session_id, camera_id = _http_ids(session_id, camera_id)
        assert session_id and camera_id
        upload_id = uuid.uuid4().hex
        staging_root = (settings.staging_dir / "uploads").resolve()
        tmp = staging_root / upload_id / f"{session_id}_{camera_id}.mp4"
        if not str(tmp.resolve()).startswith(str(staging_root)):
            raise HTTPException(status_code=400, detail="Invalid upload path")
        try:
            await _stream_upload_to_temp(file, tmp, settings.max_upload_bytes)
            parsed = SessionManifest.model_validate_json(manifest) if manifest else None
            result = store_upload(
                sessions_dir=pipe.sessions_dir,
                session_id=session_id,
                camera_id=camera_id,
                source_file=tmp,
                checksum_hex=checksum,
                manifest=parsed,
            )
            return result
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid manifest: {exc}") from exc
        except OffloadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            parent = tmp.parent
            if parent.exists() and parent.name == upload_id:
                try:
                    parent.rmdir()
                except OSError as exc:
                    logger.warning("Could not remove upload staging dir %s: %s", parent, exc)

    @router.post("/upload/confirm", dependencies=[Depends(require_ops)])
    def upload_confirm(body: UploadConfirmRequest):
        session_id, camera_id = _http_ids(body.session_id, body.camera_id)
        assert session_id and camera_id
        try:
            return confirm_upload(
                sessions_dir=pipe.sessions_dir,
                session_id=session_id,
                camera_id=camera_id,
            )
        except OffloadError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _run_process(body: ProcessRequest, db: Session):
        session_id, _ = _http_ids(body.session_id, None)
        assert session_id
        try:
            return pipe.process_session(session_id, db=db, opponent=body.opponent)
        except FFmpegError as exc:
            # Must precede FileNotFoundError handling: a missing ffmpeg binary is a
            # server fault, not a missing session.
            logger.error("Processing %s failed during stitch: %s", session_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OffloadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidIdError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/process", dependencies=[Depends(require_ops)])
    def process_session(body: ProcessRequest, db: Session = Depends(get_session)):
        return _run_process(body, db)

    @router.post("/process/from-rig", dependencies=[Depends(require_ops)])
    def process_from_rig(body: ProcessRequest, db: Session = Depends(get_session)):
        """Ingest local rig recordings (demo path) then stitch + detect events."""
        return _run_process(body, db)

    @router.get("/sessions", dependencies=[Depends(require_ops)])
    def sessions():
        return {"sessions": pipe.list_ready_sessions()}

    router.pipeline = pipe  # type: ignore[attr-defined]
    router.coordinator = coord  # type: ignore[attr-defined]
    return router
