from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from soccersnap.models import CameraAsset, Game, GameEvent
from soccersnap.protocol.checksum import sha256_file, verify_checksum
from soccersnap.protocol.manifests import SessionManifest, list_manifests, load_manifest
from soccersnap.protocol.offload import OffloadError, confirm_upload, store_upload
from soccersnap.process.events import detect_demo_events
from soccersnap.process.stitcher import stitch_hstack


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
        manifest_path = self.recordings_dir / f"{session_id}_{camera_id}.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest missing for {session_id}/{camera_id}")
        manifest = load_manifest(manifest_path)
        media = self.recordings_dir / manifest.file_name
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
        results = []
        for cam in ("CAM_L", "CAM_C", "CAM_R"):
            path = self.recordings_dir / f"{session_id}_{cam}.json"
            if path.exists():
                results.append(self.ingest_from_rig(session_id, cam, db=db))
        if not results:
            raise FileNotFoundError(f"No camera assets for session {session_id}")
        return results

    def process_session(self, session_id: str, *, db: Session, opponent: str = "Rivals") -> dict:
        ingested = self.ingest_session(session_id, db=db)
        cam_paths = []
        duration = 0.0
        for cam in ("CAM_L", "CAM_C", "CAM_R"):
            media = self.sessions_dir / session_id / cam / "recording.mp4"
            if media.exists():
                cam_paths.append(media)
                manifest_path = self.sessions_dir / session_id / cam / "manifest.json"
                if manifest_path.exists():
                    duration = max(duration, load_manifest(manifest_path).video.duration_sec)

        if len(cam_paths) < 3:
            raise RuntimeError("Need CAM_L, CAM_C, and CAM_R before processing")

        stitched = self.media_dir / f"{session_id}_stitched.mp4"
        stitch_hstack(cam_paths, stitched)

        events = detect_demo_events(duration or 10.0)
        events_path = self.media_dir / f"{session_id}_events.json"
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
        free = shutil.disk_usage(self.sessions_dir).free / (1024**3)
        return {
            "status": "healthy",
            "storage_free_gb": round(free, 2),
            "active_uploads": 0,
            "sessions_dir": str(self.sessions_dir),
        }

    def list_ready_sessions(self) -> list[str]:
        return sorted(
            p.name
            for p in self.sessions_dir.iterdir()
            if p.is_dir() and (p / "CAM_L" / "recording.mp4").exists()
        ) if self.sessions_dir.exists() else []
