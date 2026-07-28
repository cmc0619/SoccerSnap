from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from soccersnap.config import settings
from soccersnap.db import get_session
from soccersnap.protocol.manifests import SessionManifest
from soccersnap.protocol.offload import OffloadError, confirm_upload, store_upload
from soccersnap.protocol.schemas import UploadConfirmRequest
from soccersnap.process.pipeline import ProcessPipeline
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.security import require_ops


class ProcessRequest(BaseModel):
    session_id: str
    opponent: str = "Rivals"


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
        # Unique staging path so concurrent uploads never share filenames.
        upload_id = uuid.uuid4().hex
        tmp = settings.staging_dir / "uploads" / upload_id / f"{session_id}_{camera_id}.mp4"
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
        except OffloadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            parent = tmp.parent
            if parent.exists() and parent.name == upload_id:
                try:
                    parent.rmdir()
                except OSError:
                    pass

    @router.post("/upload/confirm", dependencies=[Depends(require_ops)])
    def upload_confirm(body: UploadConfirmRequest):
        try:
            return confirm_upload(
                sessions_dir=pipe.sessions_dir,
                session_id=body.session_id,
                camera_id=body.camera_id,
            )
        except OffloadError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/process", dependencies=[Depends(require_ops)])
    def process_session(body: ProcessRequest, db: Session = Depends(get_session)):
        try:
            return pipe.process_session(body.session_id, db=db, opponent=body.opponent)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/process/from-rig", dependencies=[Depends(require_ops)])
    def process_from_rig(body: ProcessRequest, db: Session = Depends(get_session)):
        """Ingest local rig recordings (demo path) then stitch + detect events."""
        try:
            return pipe.process_session(body.session_id, db=db, opponent=body.opponent)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/sessions", dependencies=[Depends(require_ops)])
    def sessions():
        return {"sessions": pipe.list_ready_sessions()}

    router.pipeline = pipe  # type: ignore[attr-defined]
    router.coordinator = coord  # type: ignore[attr-defined]
    return router
