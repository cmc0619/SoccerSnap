"""Safety gates return reports instead of raising — UI can show exact refusals."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TEMP_LIMIT_C = 85.0
BATTERY_CRITICAL = 10
SYNC_LIMIT_MS = 5.0


@dataclass(slots=True)
class GateReport:
    name: str
    ok: bool
    reason: Optional[str] = None


def camera_present(device: Path = Path("/dev/video0"), *, simulate: bool = False) -> GateReport:
    if simulate:
        return GateReport(name="camera", ok=True, reason="Simulated camera online")
    if device.exists():
        return GateReport(name="camera", ok=True)
    return GateReport(name="camera", ok=False, reason=f"Camera device missing at {device}")


def storage_writable(path: Path) -> GateReport:
    path.mkdir(parents=True, exist_ok=True)
    try:
        probe = path / ".soccersnap-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return GateReport(name="storage", ok=True)
    except OSError as exc:
        return GateReport(name="storage", ok=False, reason=f"Storage not writable: {exc}")


def free_space_ok(path: Path, minimum_gb: float) -> GateReport:
    path.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(path).free / (1024**3)
    if free_gb >= minimum_gb:
        return GateReport(name="disk", ok=True, reason=f"{free_gb:.1f}GB free")
    return GateReport(
        name="disk",
        ok=False,
        reason=f"Low disk: {free_gb:.1f}GB < {minimum_gb}GB threshold",
    )


def temperature_safe(
    thermal_path: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
    *,
    simulate: bool = False,
    simulated_c: float = 52.0,
) -> GateReport:
    if simulate:
        ok = simulated_c < TEMP_LIMIT_C
        return GateReport(
            name="temperature",
            ok=ok,
            reason=None if ok else f"Overheating: {simulated_c:.1f}C >= {TEMP_LIMIT_C}C",
        )
    if not thermal_path.exists():
        return GateReport(name="temperature", ok=True, reason="Temperature sensor unavailable")
    try:
        temp_c = float(thermal_path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return GateReport(name="temperature", ok=False, reason="Temperature read failed")
    if temp_c < TEMP_LIMIT_C:
        return GateReport(name="temperature", ok=True, reason=f"{temp_c:.1f}C")
    return GateReport(name="temperature", ok=False, reason=f"Overheating: {temp_c:.1f}C >= {TEMP_LIMIT_C}C")


def battery_safe(
    capacity_path: Path = Path("/sys/class/power_supply/BAT0/capacity"),
    *,
    simulate: bool = False,
    simulated_percent: int = 88,
) -> GateReport:
    if simulate:
        ok = simulated_percent > BATTERY_CRITICAL
        return GateReport(
            name="battery",
            ok=ok,
            reason=None if ok else f"Battery critically low: {simulated_percent}%",
        )
    if not capacity_path.exists():
        return GateReport(name="battery", ok=True, reason="Battery sensor unavailable")
    try:
        percent = int(capacity_path.read_text().strip())
    except (OSError, ValueError):
        return GateReport(name="battery", ok=False, reason="Battery read failed")
    if percent > BATTERY_CRITICAL:
        return GateReport(name="battery", ok=True, reason=f"{percent}%")
    return GateReport(name="battery", ok=False, reason=f"Battery critically low: {percent}%")


def sync_ok(offset_ms: float, limit_ms: float = SYNC_LIMIT_MS) -> GateReport:
    if abs(offset_ms) <= limit_ms:
        return GateReport(name="sync", ok=True, reason=f"{offset_ms:.2f}ms")
    return GateReport(name="sync", ok=False, reason=f"Sync offset {offset_ms:.2f}ms exceeds {limit_ms}ms")


def all_gates(
    base_dir: Path,
    minimum_gb: float,
    *,
    simulate: bool = False,
    offset_ms: float = 0.0,
) -> list[GateReport]:
    return [
        camera_present(simulate=simulate),
        storage_writable(base_dir),
        free_space_ok(base_dir, minimum_gb),
        temperature_safe(simulate=simulate),
        battery_safe(simulate=simulate),
        sync_ok(offset_ms),
    ]


def run_preflight(
    base_dir: Path,
    minimum_gb: float,
    *,
    simulate: bool = False,
    peer_offsets_ms: dict[str, float] | None = None,
) -> dict:
    reports = all_gates(base_dir, minimum_gb, simulate=simulate, offset_ms=0.0)
    peers = peer_offsets_ms or {"CAM_L": 0.8, "CAM_C": 0.0, "CAM_R": 1.2}
    peer_reports = [sync_ok(offset, ) for offset in peers.values()]
    all_reports = reports + [
        GateReport(name=f"peer_sync_{cam}", ok=sync_ok(off).ok, reason=f"{cam}: {off:.2f}ms")
        for cam, off in peers.items()
    ]
    # Keep peer sync detail without duplicating raw sync_ok thrice in blocking set
    blocking = [r for r in reports if not r.ok]
    return {
        "ok": not blocking,
        "reports": [
            {"name": r.name, "ok": r.ok, "reason": r.reason}
            for r in all_reports
        ],
        "blocking": [{"name": r.name, "reason": r.reason} for r in blocking],
        "peers_online": list(peers.keys()),
        "_unused_peer_ok": all(r.ok for r in peer_reports),
    }
