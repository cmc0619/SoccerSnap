from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from soccersnap.models import CameraAsset, Game, GameEvent
from soccersnap.paths import UnsafePathError, free_gb, is_safe_name, resolve_within
from soccersnap.protocol.ids import CAMERA_IDS, validate_camera_id, validate_session_id
from soccersnap.protocol.manifests import load_manifest
from soccersnap.protocol.offload import OffloadError, confirm_upload, store_upload
from soccersnap.process.events import detect_demo_events
from soccersnap.process.stitcher import stitch_hstack


def _within(root: Path, *parts: str | Path, what: str) -> Path:
    try:
        return resolve_within(root, *parts)
    except UnsafePathError as exc:
        raise OffloadError(f"Invalid {what} path") from exc


class ProcessPipeline:
    def __init__(self, sessions_dir: Path, media_dir: Path, recordings_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.media_dir = media_dir
        self.recordings_dir = recordings_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def ingest_from_rig(
        self,
        session_id: str,
        camera_id: str,
        *,
        db: Session | None = None,
    ) -> dict:
        session_id = validate_session_id(session_id)
        camera_id = validate_camera_id(camera_id)
        manifest_path = _within(
            self.recordings_dir, f"{session_id}_{camera_id}.json", what="recording"
        )
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest missing for {session_id}/{camera_id}")
        manifest = load_manifest(manifest_path)
        if not is_safe_name(manifest.file_name):
            raise OffloadError("Invalid media file name in manifest")
        media = _within(self.recordings_dir, manifest.file_name, what="recording media")
        if not media.exists():
            raise FileNotFoundError(f"Media missing: {media}")

        result = store_upload(
            sessions_dir=self.sessions_dir,
            session_id=session_id,
            camera_id=camera_id,
            source_file=media,
            checksum_hex=manifest.checksum.value,
            manifest=manifest,
        )
        confirmed = confirm_upload(
            sessions_dir=self.sessions_dir,
            session_id=session_id,
            camera_id=camera_id,
        )
        if confirmed["checksum_sha256"].lower() != manifest.checksum.value.lower():
            raise OffloadError("Confirm checksum mismatch")

        if db is not None:
            asset = (
                db.query(CameraAsset)
                .filter_by(session_id=session_id, camera_id=camera_id)
                .one_or_none()
            )
            if asset is None:
                asset = CameraAsset(session_id=session_id, camera_id=camera_id)
                db.add(asset)
            asset.file_name = manifest.file_name
            asset.checksum = manifest.checksum.value
            asset.offset_ms = manifest.offset_ms
            asset.duration_sec = manifest.video.duration_sec
            asset.path = result["path"]
            asset.confirmed = True
            game = db.query(Game).filter_by(session_id=session_id).one_or_none()
            if game:
                asset.game_id = game.id
                if game.status in ("scheduled", "recording"):
                    game.status = "processing"
            db.flush()

        return {**result, "confirm": confirmed, "manifest": manifest.model_dump(mode="json")}

    def ingest_session(self, session_id: str, *, db: Session | None = None) -> list[dict]:
        session_id = validate_session_id(session_id)
        results = []
        for cam in CAMERA_IDS:
            path = self.recordings_dir / f"{session_id}_{cam}.json"
            if path.exists():
                results.append(self.ingest_from_rig(session_id, cam, db=db))
        if not results:
            raise FileNotFoundError(f"No camera assets for session {session_id}")
        return results

    def process_session(self, session_id: str, *, db: Session, opponent: str = "Rivals") -> dict:
        session_id = validate_session_id(session_id)
        ingested = self.ingest_session(session_id, db=db)
        cam_paths = []
        duration = 0.0
        for cam in CAMERA_IDS:
            media = _within(
                self.sessions_dir, session_id, cam, "recording.mp4", what="session media"
            )
            if media.exists():
                cam_paths.append(media)
                manifest_path = media.parent / "manifest.json"
                if manifest_path.exists():
                    duration = max(duration, load_manifest(manifest_path).video.duration_sec)

        if len(cam_paths) < len(CAMERA_IDS):
            raise RuntimeError(f"Need {', '.join(CAMERA_IDS)} before processing")

        stitched = _within(self.media_dir, f"{session_id}_stitched.mp4", what="media output")
        stitch_hstack(cam_paths, stitched)

        events = detect_demo_events(duration or 10.0)
        events_path = stitched.with_name(f"{session_id}_events.json")
        events_path.write_text(json.dumps(events, indent=2), encoding="utf-8")

        game = db.query(Game).filter_by(session_id=session_id).one_or_none()
        if game is None:
            # Attach to first team if present via caller; create bare game otherwise.
            from soccersnap.models import Team

            team = db.query(Team).first()
            if team is None:
                team = Team(name="SoccerSnap FC", team_code="SNAP26")
                db.add(team)
                db.flush()
            game = Game(
                session_id=session_id,
                team_id=team.id,
                opponent=opponent,
                status="processing",
            )
            db.add(game)
            db.flush()

        game.video_path = f"/media/{stitched.name}"
        game.duration_sec = duration
        game.status = "ready"
        game.opponent = opponent or game.opponent

        db.query(GameEvent).filter_by(game_id=game.id).delete()
        for event in events:
            db.add(
                GameEvent(
                    game_id=game.id,
                    type=event["type"],
                    t_start_ms=event["t_start_ms"],
                    t_end_ms=event["t_end_ms"],
                    confidence=event["confidence"],
                    jersey_number=event.get("jersey_number"),
                    label=event.get("label", ""),
                    payload_json=json.dumps(event.get("payload") or {}),
                )
            )
        for asset in db.query(CameraAsset).filter_by(session_id=session_id):
            asset.game_id = game.id
        db.flush()

        return {
            "session_id": session_id,
            "game_id": game.id,
            "status": game.status,
            "video_path": game.video_path,
            "events": len(events),
            "ingested": len(ingested),
            "stitched": str(stitched),
        }

    def health(self) -> dict:
        return {
            "status": "healthy",
            "storage_free_gb": round(free_gb(self.sessions_dir), 2),
            "active_uploads": 0,
            "sessions_dir": str(self.sessions_dir),
        }

    def list_ready_sessions(self) -> list[str]:
        return sorted(
            p.name
            for p in self.sessions_dir.iterdir()
            if p.is_dir() and (p / "CAM_L" / "recording.mp4").exists()
        ) if self.sessions_dir.exists() else []
