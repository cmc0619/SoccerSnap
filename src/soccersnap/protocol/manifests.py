"""Recording manifests — Claude PROTOCOL nested shape + Chat flat handoff fields."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from .checksum import sha256_file

logger = logging.getLogger(__name__)


class CameraId(str, Enum):
    CAM_L = "CAM_L"
    CAM_C = "CAM_C"
    CAM_R = "CAM_R"


CAMERA_POSITION = {
    CameraId.CAM_L: "left",
    CameraId.CAM_C: "center",
    CameraId.CAM_R: "right",
}


class ChecksumBlock(BaseModel):
    algorithm: str = "sha256"
    value: str


class RecordingBlock(BaseModel):
    id: str
    session_id: str
    camera_id: CameraId
    position: str


class FileBlock(BaseModel):
    name: str
    size_bytes: int
    container: str = "mp4"
    codec: str = "h264"


class ResolutionBlock(BaseModel):
    width: int = 1280
    height: int = 720


class VideoBlock(BaseModel):
    resolution: ResolutionBlock = Field(default_factory=ResolutionBlock)
    fps: int = 30
    bitrate_mbps: float = 8.0
    duration_sec: float = 0.0


class TimingBlock(BaseModel):
    start_time: str
    end_time: str
    ntp_synced: bool = True
    sync_offset_ms: float = 0.0
    scheduled_start: str | None = None


class DeviceBlock(BaseModel):
    hostname: str = "soccersnap"
    ip_address: str = "127.0.0.1"
    software_version: str = "1.0.0"


class QualityBlock(BaseModel):
    dropped_frames: int = 0
    temperature_avg_c: float = 52.0
    temperature_max_c: float = 58.0
    framing_quality: str = "good"


class SessionManifest(BaseModel):
    """PROTOCOL.md nested manifest with Chat-compatible flat accessors."""

    version: str = "1.0"
    recording: RecordingBlock
    file: FileBlock
    video: VideoBlock
    timing: TimingBlock
    checksum: ChecksumBlock
    device: DeviceBlock = Field(default_factory=DeviceBlock)
    quality: QualityBlock = Field(default_factory=QualityBlock)
    # Chat lean handoff fields (also written for stitch/ML consumers)
    offloaded: bool = False
    offset_ms: float = 0.0

    @property
    def session_id(self) -> str:
        return self.recording.session_id

    @property
    def camera_id(self) -> CameraId:
        return self.recording.camera_id

    @property
    def file_name(self) -> str:
        return self.file.name

    def path_for(self, directory: Path) -> Path:
        return directory / f"{self.recording.session_id}_{self.recording.camera_id.value}.json"

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(directory)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    def flat(self) -> dict[str, Any]:
        """Chat-style flat view used by listings and UI."""
        return {
            "session_id": self.session_id,
            "camera_id": self.camera_id.value,
            "recording_id": self.recording.id,
            "file": self.file.name,
            "file_name": self.file.name,
            "start_time_local": self.timing.start_time,
            "start_time_master": self.timing.start_time,
            "offset_ms": self.offset_ms,
            "sync_offset_ms": self.timing.sync_offset_ms,
            "scheduled_start": self.timing.scheduled_start,
            "duration": self.video.duration_sec,
            "duration_sec": self.video.duration_sec,
            "resolution": f"{self.video.resolution.width}x{self.video.resolution.height}",
            "fps": self.video.fps,
            "codec": self.file.codec,
            "dropped_frames": self.quality.dropped_frames,
            "checksum": {"algo": self.checksum.algorithm, "value": self.checksum.value},
            "offloaded": self.offloaded,
            "software_version": self.device.software_version,
            "framing_quality": self.quality.framing_quality,
        }


def parse_resolution(resolution: str) -> ResolutionBlock:
    """Parse `WxH`, falling back to the default resolution with a warning."""
    try:
        w, h = resolution.lower().split("x", 1)
        return ResolutionBlock(width=int(w), height=int(h))
    except (AttributeError, ValueError, ValidationError) as exc:
        default = ResolutionBlock()
        logger.warning(
            "Unparseable resolution %r (%s); defaulting to %dx%d",
            resolution,
            exc,
            default.width,
            default.height,
        )
        return default


def create_manifest(
    *,
    session_id: str,
    camera_id: CameraId | str,
    media_path: Path,
    offset_ms: float = 0.0,
    duration_sec: float = 0.0,
    software_version: str = "1.0.0",
    framing_quality: str = "good",
    resolution: str = "1280x720",
    fps: int = 30,
    codec: str = "h264",
    scheduled_start: datetime | None = None,
    temperature_c: float = 52.0,
    hostname: str | None = None,
) -> SessionManifest:
    cam = CameraId(camera_id)
    start = scheduled_start or datetime.now(timezone.utc)
    end = start + timedelta(seconds=duration_sec)
    recording_id = f"{session_id}_{cam.value}"
    size = media_path.stat().st_size if media_path.exists() else 0
    return SessionManifest(
        recording=RecordingBlock(
            id=recording_id,
            session_id=session_id,
            camera_id=cam,
            position=CAMERA_POSITION[cam],
        ),
        file=FileBlock(
            name=media_path.name,
            size_bytes=size,
            codec=codec,
        ),
        video=VideoBlock(
            resolution=parse_resolution(resolution),
            fps=fps,
            duration_sec=duration_sec,
        ),
        timing=TimingBlock(
            start_time=start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            end_time=end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            ntp_synced=True,
            sync_offset_ms=offset_ms,
            scheduled_start=(
                scheduled_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if scheduled_start
                else None
            ),
        ),
        checksum=ChecksumBlock(value=sha256_file(media_path)),
        device=DeviceBlock(
            hostname=hostname or f"soccersnap-{cam.value.lower()}",
            software_version=software_version,
        ),
        quality=QualityBlock(
            temperature_avg_c=temperature_c,
            temperature_max_c=temperature_c + 4.0,
            framing_quality=framing_quality,
        ),
        offloaded=False,
        offset_ms=offset_ms,
    )


def load_manifest(path: Path) -> SessionManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Accept Chat flat manifests by normalizing upward if needed.
    if "recording" not in data and "session_id" in data:
        cam = CameraId(data["camera_id"])
        file_name = data.get("file") or data.get("file_name")
        checksum = data.get("checksum") or {}
        res = parse_resolution(data.get("resolution", "1280x720"))
        data = {
            "version": "1.0",
            "recording": {
                "id": f"{data['session_id']}_{cam.value}",
                "session_id": data["session_id"],
                "camera_id": cam.value,
                "position": CAMERA_POSITION[cam],
            },
            "file": {
                "name": file_name,
                "size_bytes": data.get("size_bytes", 0),
                "container": "mp4",
                "codec": data.get("codec", "h264"),
            },
            "video": {
                "resolution": res.model_dump(),
                "fps": data.get("fps", 30),
                "bitrate_mbps": data.get("bitrate_mbps", 8.0),
                "duration_sec": data.get("duration") or data.get("duration_sec") or 0.0,
            },
            "timing": {
                "start_time": data.get("start_time_local"),
                "end_time": data.get("ended_at") or data.get("start_time_local"),
                "ntp_synced": True,
                "sync_offset_ms": data.get("offset_ms", 0.0),
                "scheduled_start": data.get("scheduled_start"),
            },
            "checksum": {
                "algorithm": checksum.get("algo") or checksum.get("algorithm") or "sha256",
                "value": checksum.get("value", ""),
            },
            "device": {
                "hostname": f"soccersnap-{cam.value.lower()}",
                "ip_address": "127.0.0.1",
                "software_version": data.get("software_version", "1.0.0"),
            },
            "quality": {
                "dropped_frames": data.get("dropped_frames", 0),
                "temperature_avg_c": 52.0,
                "temperature_max_c": 58.0,
                "framing_quality": data.get("framing_quality", "good"),
            },
            "offloaded": data.get("offloaded", False),
            "offset_ms": data.get("offset_ms", 0.0),
        }
    return SessionManifest.model_validate(data)


def mark_offloaded(directory: Path, session_id: str, camera_id: CameraId | str) -> Optional[SessionManifest]:
    cam = CameraId(camera_id)
    path = directory / f"{session_id}_{cam.value}.json"
    if not path.exists():
        return None
    manifest = load_manifest(path)
    manifest.offloaded = True
    manifest.write(directory)
    return manifest


def list_manifests(directory: Path) -> list[SessionManifest]:
    if not directory.exists():
        return []
    out: list[SessionManifest] = []
    for path in sorted(directory.glob("*.json")):
        try:
            out.append(load_manifest(path))
        except (OSError, ValueError, ValidationError) as exc:
            # A single unreadable manifest must not hide the rest of the fleet.
            logger.error("Skipping unreadable manifest %s: %s", path, exc)
    return out
