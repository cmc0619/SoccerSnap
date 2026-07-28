from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from soccersnap.config import settings
from soccersnap.media import FFmpegError, run_ffmpeg
from soccersnap.protocol.checksum import verify_checksum
from soccersnap.protocol.manifests import (
    CameraId,
    SessionManifest,
    create_manifest,
    list_manifests,
    load_manifest,
    mark_offloaded,
)
from soccersnap.protocol.schemas import ConfirmRequest, DiskStatus, SyncStatus
from soccersnap.rig.framing import assess_framing

logger = logging.getLogger(__name__)


class RecorderError(Exception):
    """One or more cameras failed to produce a recording."""


@dataclass
class CameraNode:
    camera_id: CameraId
    offset_ms: float = 0.0
    temperature_c: float = 51.0
    battery_percent: int = 90
    recording: bool = False
    session_id: str | None = None
    started_at: float | None = None
    scheduled_start: datetime | None = None


@dataclass
class RecorderFleet:
    base_dir: Path
    simulate: bool = True
    nodes: dict[str, CameraNode] = field(default_factory=dict)
    software_version: str = "1.0.0"

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.nodes:
            self.nodes = {
                "CAM_L": CameraNode(CameraId.CAM_L, offset_ms=0.8, battery_percent=86),
                "CAM_C": CameraNode(CameraId.CAM_C, offset_ms=0.0, battery_percent=92),
                "CAM_R": CameraNode(CameraId.CAM_R, offset_ms=1.1, battery_percent=88),
            }

    def disk_status(self) -> DiskStatus:
        usage = shutil.disk_usage(self.base_dir)
        total = usage.total / (1024**3)
        free = usage.free / (1024**3)
        used = usage.used / (1024**3)
        return DiskStatus(
            total_gb=round(total, 2),
            free_gb=round(free, 2),
            used_gb=round(used, 2),
            free_percent=round(100.0 * free / total, 1) if total else None,
            estimated_minutes_remaining=int(free * 60 / 8) if free else 0,  # ~8GB/hr rough
        )

    def status(self) -> dict:
        cams = []
        for node in self.nodes.values():
            framing = assess_framing(node.camera_id.value, simulate=self.simulate)
            role = "master" if node.camera_id == CameraId.CAM_C else "client"
            sync = SyncStatus(role=role, offset_ms=node.offset_ms, confidence="high")
            cams.append(
                {
                    "camera_id": node.camera_id.value,
                    "recording": node.recording,
                    "session_id": node.session_id,
                    "offset_ms": node.offset_ms,
                    "temperature_c": node.temperature_c,
                    "battery_percent": node.battery_percent,
                    "scheduled_start": (
                        node.scheduled_start.isoformat().replace("+00:00", "Z")
                        if node.scheduled_start
                        else None
                    ),
                    "sync": sync.model_dump(mode="json"),
                    "disk": self.disk_status().model_dump(),
                    "framing": {
                        "quality": framing.quality.value,
                        "score": framing.score,
                        "message": framing.message,
                        "tone_hz": framing.tone_hz,
                    },
                }
            )
        return {
            "recording": any(n.recording for n in self.nodes.values()),
            "session_id": next((n.session_id for n in self.nodes.values() if n.session_id), None),
            "cameras": cams,
            "disk": self.disk_status().model_dump(),
        }

    def _media_path(self, session_id: str, camera_id: str) -> Path:
        # PROTOCOL-ish recording id filename
        return self.base_dir / f"{session_id}_{camera_id}.mp4"

    def _write_simulated_clip(self, path: Path, duration_sec: float, label: str) -> None:
        duration_sec = max(2.0, float(duration_sec))
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x0B3D2E:s=1280x720:d={duration_sec}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={min(0.4, duration_sec)}",
            "-vf",
            (
                f"drawtext=text='SoccerSnap {label}':fontsize=48:fontcolor=white:"
                "x=(w-text_w)/2:y=(h-text_h)/2,"
                "drawgrid=width=160:height=90:thickness=1:color=white@0.15"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
        run_ffmpeg(cmd, timeout=120, context=f"Write clip for {label}")

    def start(self, session_id: str, scheduled_start: datetime | None = None) -> dict:
        if any(n.recording for n in self.nodes.values()):
            raise RuntimeError("Already recording")
        for node in self.nodes.values():
            node.recording = True
            node.session_id = session_id
            node.started_at = time.time()
            node.scheduled_start = scheduled_start
        return self.status()

    def stop(self, duration_sec: float | None = None) -> list[SessionManifest]:
        if not any(n.recording for n in self.nodes.values()):
            raise RuntimeError("Not recording")
        manifests: list[SessionManifest] = []
        failures: list[str] = []
        for node in self.nodes.values():
            elapsed = time.time() - (node.started_at or time.time())
            dur = float(duration_sec) if duration_sec is not None else max(3.0, min(elapsed, 12.0))
            media = self._media_path(node.session_id or "session", node.camera_id.value)
            framing = assess_framing(node.camera_id.value, simulate=self.simulate)
            try:
                self._write_simulated_clip(media, dur, node.camera_id.value)
                manifest = create_manifest(
                    session_id=node.session_id or "session",
                    camera_id=node.camera_id,
                    media_path=media,
                    offset_ms=node.offset_ms,
                    duration_sec=dur,
                    software_version=self.software_version,
                    framing_quality=framing.quality.value,
                    scheduled_start=node.scheduled_start,
                    temperature_c=node.temperature_c,
                )
                manifest.write(self.base_dir)
                manifests.append(manifest)
            except (FFmpegError, OSError) as exc:
                logger.exception("Stop failed for %s", node.camera_id.value)
                failures.append(f"{node.camera_id.value}: {exc}")
            finally:
                # Never leave the fleet wedged in "recording" after a failed stop.
                node.recording = False
                node.started_at = None
        if failures:
            raise RecorderError(
                f"{len(failures)} of {len(self.nodes)} cameras failed to stop: "
                + "; ".join(failures)
            )
        return manifests

    def recordings(self) -> list[dict]:
        out = []
        for manifest in list_manifests(self.base_dir):
            media = self.base_dir / manifest.file_name
            flat = manifest.flat()
            flat.update(
                {
                    "exists": media.exists(),
                    "size_bytes": media.stat().st_size if media.exists() else 0,
                    "manifest": manifest.model_dump(mode="json"),
                }
            )
            out.append(flat)
        return out

    def confirm(self, request: ConfirmRequest) -> SessionManifest:
        """Chat ConfirmRequest: refuse on checksum mismatch, then mark offloaded."""
        path = self.base_dir / f"{request.session_id}_{request.camera_id}.json"
        if not path.exists():
            raise FileNotFoundError("Manifest not found")
        manifest = load_manifest(path)
        if manifest.file_name != request.file:
            raise ValueError("File name does not match manifest")
        media = self.base_dir / manifest.file_name
        if not media.exists():
            raise FileNotFoundError("Media missing")
        if request.checksum.algo.lower() != "sha256":
            raise ValueError("Unsupported checksum algorithm")
        if not verify_checksum(media, request.checksum.value):
            raise ValueError("Checksum mismatch — refusing offload confirm")
        if manifest.checksum.value.lower() != request.checksum.value.lower():
            raise ValueError("Checksum mismatch against stored manifest")
        marked = mark_offloaded(self.base_dir, request.session_id, request.camera_id)
        if marked is None:
            raise FileNotFoundError("Manifest not found after confirm")
        return marked

    def cleanup_offloaded(self) -> dict[str, list[str]]:
        """Delete offloaded media/manifests, reporting per-file failures."""
        removed: list[str] = []
        failed: list[str] = []
        for manifest in list_manifests(self.base_dir):
            if not manifest.offloaded:
                continue
            media = self.base_dir / manifest.file_name
            json_path = manifest.path_for(self.base_dir)
            for path in (media, json_path):
                if not path.exists():
                    continue
                try:
                    path.unlink()
                except OSError as exc:
                    logger.error("Cleanup could not delete %s: %s", path, exc)
                    failed.append(f"{path}: {exc}")
                else:
                    removed.append(str(path))
        return {"removed": removed, "failed": failed}


def default_fleet() -> RecorderFleet:
    settings.ensure_dirs()
    return RecorderFleet(
        base_dir=settings.recordings_dir,
        simulate=settings.simulate_hardware,
        software_version=settings.software_version,
    )
