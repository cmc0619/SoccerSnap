from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from soccersnap.config import settings
from soccersnap.protocol.gates import run_preflight
from soccersnap.rig.recorder import RecorderFleet, default_fleet


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("GAME_%Y%m%d_%H%M%S")


class FleetCoordinator:
    """
    CAM_C-style coordinator with Claude scheduled-start semantics.

    Broadcasts a future `scheduled_start` (default: now + 2s). Every camera
    waits until that master clock instant before recording begins.
    """

    def __init__(self, fleet: RecorderFleet | None = None) -> None:
        self.fleet = fleet or default_fleet()
        self._last_scheduled_start: datetime | None = None
        self._current_session: str | None = None

    def peers(self) -> list[dict]:
        status = self.fleet.status()
        return [
            {
                "camera_id": cam["camera_id"],
                "is_local": cam["camera_id"] == "CAM_C",
                "online": True,
                "offset_ms": cam["offset_ms"],
                "recording": cam["recording"],
                "framing": cam["framing"],
            }
            for cam in status["cameras"]
        ]

    def preflight(self) -> dict:
        peers = {cid: node.offset_ms for cid, node in self.fleet.nodes.items()}
        result = run_preflight(
            self.fleet.base_dir,
            settings.min_free_gb,
            simulate=self.fleet.simulate,
            peer_offsets_ms=peers,
        )
        status = self.fleet.status()
        framing_ok = all(cam["framing"]["quality"] != "no_field" for cam in status["cameras"])
        if not framing_ok:
            result["ok"] = False
            result["blocking"].append({"name": "framing", "reason": "One or more cameras show no field"})
        result["status"] = status
        result["peers"] = self.peers()
        return result

    def start_all(
        self,
        session_id: str | None = None,
        *,
        delay_sec: float = 2.0,
        sleep_fn=time.sleep,
    ) -> dict:
        pre = self.preflight()
        if not pre["ok"]:
            return {"success": False, "started": False, "preflight": pre, "message": "Preflight failed"}

        if any(n.recording for n in self.fleet.nodes.values()):
            return {
                "success": False,
                "started": False,
                "error": "Recording already in progress",
                "session_id": self._current_session,
            }

        sid = session_id or new_session_id()
        master_time = datetime.now(timezone.utc)
        scheduled = master_time + timedelta(seconds=max(0.0, delay_sec))
        self._last_scheduled_start = scheduled
        self._current_session = sid

        cameras: dict[str, dict] = {}
        # In-process fleet: wait once to the scheduled instant, then start all.
        wait = (scheduled - datetime.now(timezone.utc)).total_seconds()
        if wait > 0:
            sleep_fn(wait)

        status = self.fleet.start(sid, scheduled_start=scheduled)
        for cam in status["cameras"]:
            cameras[cam["camera_id"]] = {
                "success": True,
                "session_id": sid,
                "scheduled_start": scheduled.isoformat().replace("+00:00", "Z"),
            }

        return {
            "success": True,
            "started": True,
            "session_id": sid,
            "scheduled_start": scheduled.isoformat().replace("+00:00", "Z"),
            "master_time": master_time.isoformat().replace("+00:00", "Z"),
            "cameras": cameras,
            "status": status,
            "preflight": pre,
            "message": "All cameras started",
        }

    def stop_all(self, duration_sec: float | None = None) -> dict:
        manifests = self.fleet.stop(duration_sec=duration_sec)
        return {
            "success": True,
            "stopped": True,
            "session_id": manifests[0].session_id if manifests else self._current_session,
            "manifests": [m.model_dump(mode="json") for m in manifests],
            "flat_manifests": [m.flat() for m in manifests],
            "status": self.fleet.status(),
        }

    def aggregated_status(self) -> dict:
        status = self.fleet.status()
        return {
            "coordinator": "CAM_C",
            "session_id": self._current_session or status.get("session_id"),
            "scheduled_start": (
                self._last_scheduled_start.isoformat().replace("+00:00", "Z")
                if self._last_scheduled_start
                else None
            ),
            "recording": status["recording"],
            "peers": self.peers(),
            "cameras": status["cameras"],
        }
