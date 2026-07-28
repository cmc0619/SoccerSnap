"""Claude PROTOCOL.md upload flow with checksum verify + exponential backoff."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from soccersnap.protocol.checksum import sha256_file, verify_checksum
from soccersnap.protocol.manifests import SessionManifest, load_manifest, mark_offloaded

# PROTOCOL.md retry table
BACKOFF_SECONDS = (0, 5, 10, 20, 40)

_UPLOAD_LOCKS: dict[str, threading.Lock] = {}
_UPLOAD_LOCKS_GUARD = threading.Lock()


class OffloadError(Exception):
    pass


def _destination_lock(session_id: str, camera_id: str) -> threading.Lock:
    key = f"{session_id}:{camera_id}"
    with _UPLOAD_LOCKS_GUARD:
        lock = _UPLOAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _UPLOAD_LOCKS[key] = lock
        return lock


def store_upload(
    *,
    sessions_dir: Path,
    session_id: str,
    camera_id: str,
    source_file: Path,
    checksum_hex: str,
    manifest: SessionManifest | None = None,
) -> dict:
    """Server-side: receive file, verify SHA-256, store under sessions/{id}/{cam}/."""
    if not verify_checksum(source_file, checksum_hex):
        raise OffloadError("Checksum mismatch on upload")

    dest_dir = sessions_dir / session_id / camera_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_media = dest_dir / "recording.mp4"
    dest_manifest = dest_dir / "manifest.json"
    # Serialize per camera destination + unique temp + atomic replace.
    with _destination_lock(session_id, camera_id):
        tmp_media = dest_dir / f".recording.{uuid.uuid4().hex}.mp4"
        server_checksum = ""
        try:
            shutil.copy2(source_file, tmp_media)
            server_checksum = sha256_file(tmp_media)
            if server_checksum.lower() != checksum_hex.lower():
                raise OffloadError("Post-copy checksum mismatch")
            tmp_media.replace(dest_media)
            if manifest is not None:
                dest_manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            tmp_media.unlink(missing_ok=True)
            raise

        return {
            "success": True,
            "recording_id": f"{session_id}_{camera_id}",
            "file_size": dest_media.stat().st_size,
            "checksum_verified": True,
            "checksum_sha256": server_checksum,
            "path": str(dest_media),
        }


def confirm_upload(*, sessions_dir: Path, session_id: str, camera_id: str) -> dict:
    media = sessions_dir / session_id / camera_id / "recording.mp4"
    if not media.exists():
        raise OffloadError("Recording not found on server")
    return {
        "success": True,
        "session_id": session_id,
        "camera_id": camera_id,
        "file_size": media.stat().st_size,
        "checksum_sha256": sha256_file(media),
    }


def offload_with_retry(
    *,
    local_media: Path,
    local_manifest_path: Path,
    upload_fn: Callable[[Path, str, SessionManifest], dict],
    confirm_fn: Callable[[str, str], dict],
    mark_dir: Path,
    max_attempts: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """
    Pi-side PROTOCOL flow:
      upload → verify → confirm → compare checksums → mark offloaded
    """
    manifest = load_manifest(local_manifest_path)
    session_id = manifest.session_id
    camera_id = manifest.camera_id.value
    expected = manifest.checksum.value
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        if attempt < len(BACKOFF_SECONDS):
            delay = BACKOFF_SECONDS[attempt]
            if delay:
                sleep_fn(delay)
        try:
            uploaded = upload_fn(local_media, expected, manifest)
            if not uploaded.get("checksum_verified"):
                raise OffloadError("Server did not verify checksum")
            confirmed = confirm_fn(session_id, camera_id)
            server_checksum = confirmed.get("checksum_sha256", "")
            if server_checksum.lower() != expected.lower():
                raise OffloadError("Confirm checksum mismatch — will retry upload")
            marked = mark_offloaded(mark_dir, session_id, camera_id)
            return {
                "success": True,
                "attempts": attempt + 1,
                "session_id": session_id,
                "camera_id": camera_id,
                "checksum_sha256": server_checksum,
                "offloaded": bool(marked and marked.offloaded),
            }
        except OffloadError as exc:
            last_error = exc
            continue
        except Exception as exc:  # network-ish
            last_error = OffloadError(str(exc))
            continue

    raise OffloadError(f"Offload failed after {max_attempts} attempts: {last_error}")
