"""Lean API/status models — shaped after Traloxolcus-Chat's soccer_rig/models.py."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DiskStatus(BaseModel):
    total_gb: float
    free_gb: float
    used_gb: float | None = None
    free_percent: float | None = None
    estimated_minutes_remaining: int | None = None


class SyncStatus(BaseModel):
    role: Literal["master", "client"] = "client"
    offset_ms: float = 0.0
    confidence: str = "unknown"
    master_timestamp: datetime | None = None
    local_timestamp: datetime | None = None


class Checksum(BaseModel):
    algo: str = Field(default="sha256", description="Checksum algorithm such as sha256")
    value: str = Field(..., description="Hex digest of the file")


class ConfirmRequest(BaseModel):
    """Chat-style confirm: client proves SHA-256 before the node marks offloaded."""

    session_id: str
    camera_id: str
    file: str
    checksum: Checksum


class UploadConfirmRequest(BaseModel):
    """PROTOCOL.md confirm after server-side verify."""

    session_id: str
    camera_id: str


class RecordingState(BaseModel):
    active: bool = False
    file_name: str | None = None
    session_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    scheduled_start: datetime | None = None
    eta_seconds: int | None = None
    elapsed_seconds: int | None = None


class StatusResponse(BaseModel):
    camera_id: str
    recording: RecordingState
    disk: DiskStatus
    sync: SyncStatus
    temperature_c: float | None = None
    battery_percent: int | None = None
    warnings: list[str] = Field(default_factory=list)
    framing_quality: str | None = None


class StartRecordingRequest(BaseModel):
    session_id: str | None = None
    duration_minutes: int | None = None
    audio_enabled: bool | None = None
    test_mode: bool = False
    scheduled_start: datetime | None = None
    master_time: datetime | None = None


class CoordinatorStartRequest(BaseModel):
    session_id: str | None = None
    delay_sec: float = Field(default=2.0, ge=0.0, le=30.0)
    duration_sec: float | None = Field(default=None, ge=2.0, le=600.0)


class RecordingDescriptor(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    camera_id: str
    file_name: str
    path: str
    manifest_path: str
    start_time_local: datetime
    start_time_master: datetime | None = None
    duration_seconds: float | None = None
    codec: str = "h264"
    resolution: str = "1280x720"
    fps: int = 30
    bitrate_mbps: float = 8.0
    audio_enabled: bool = True
    dropped_frames: int = 0
    offloaded: bool = False
    checksum_sha256: str | None = None
    sync_offset_ms: float = 0.0


class SelfTestResult(BaseModel):
    passed: bool
    details: list[str] = Field(default_factory=list)
    free_gb: float | None = None
