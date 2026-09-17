"""Safety gates return reports instead of raising — UI can show exact refusals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from soccersnap.paths import free_gb

T = TypeVar("T")

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
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".soccersnap-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return GateReport(name="storage", ok=True)
    except OSError as exc:
        return GateReport(name="storage", ok=False, reason=f"Storage not writable: {exc}")


def free_space_ok(path: Path, minimum_gb: float) -> GateReport:
    try:
        path.mkdir(parents=True, exist_ok=True)
        free = free_gb(path)
    except OSError as exc:
        return GateReport(name="disk", ok=False, reason=f"Disk inspection failed: {exc}")
    if free >= minimum_gb:
        return GateReport(name="disk", ok=True, reason=f"{free:.1f}GB free")
    return GateReport(
        name="disk",
        ok=False,
        reason=f"Low disk: {free:.1f}GB < {minimum_gb}GB threshold",
    )


def _sensor_gate(
    name: str,
    sensor_path: Path,
    *,
    parse: Callable[[str], T],
    simulated: T | None,
    within_limits: Callable[[T], bool],
    describe: Callable[[T], str],
    refuse: Callable[[T], str],
) -> GateReport:
    """Sysfs sensor gate: simulated reading, missing sensor, unreadable, or verdict."""
    reading = simulated
    if reading is None:
        if not sensor_path.exists():
            return GateReport(name=name, ok=True, reason=f"{name.capitalize()} sensor unavailable")
        try:
            reading = parse(sensor_path.read_text().strip())
        except (OSError, ValueError):
            return GateReport(name=name, ok=False, reason=f"{name.capitalize()} read failed")
    if within_limits(reading):
        # A simulated pass measured nothing, so it reports no reading.
        return GateReport(name=name, ok=True, reason=None if simulated is not None else describe(reading))
    return GateReport(name=name, ok=False, reason=refuse(reading))


def temperature_safe(
    thermal_path: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
    *,
    simulate: bool = False,
    simulated_c: float = 52.0,
) -> GateReport:
    return _sensor_gate(
        "temperature",
        thermal_path,
        parse=lambda raw: float(raw) / 1000.0,
        simulated=simulated_c if simulate else None,
        within_limits=lambda temp_c: temp_c < TEMP_LIMIT_C,
        describe=lambda temp_c: f"{temp_c:.1f}C",
        refuse=lambda temp_c: f"Overheating: {temp_c:.1f}C >= {TEMP_LIMIT_C}C",
    )


def battery_safe(
    capacity_path: Path = Path("/sys/class/power_supply/BAT0/capacity"),
    *,
    simulate: bool = False,
    simulated_percent: int = 88,
) -> GateReport:
    return _sensor_gate(
        "battery",
        capacity_path,
        parse=int,
        simulated=simulated_percent if simulate else None,
        within_limits=lambda percent: percent > BATTERY_CRITICAL,
        describe=lambda percent: f"{percent}%",
        refuse=lambda percent: f"Battery critically low: {percent}%",
    )


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
    peer_reports = [
        GateReport(
            name=f"peer_sync_{cam}",
            ok=(rep := sync_ok(off)).ok,
            reason=rep.reason or f"{cam}: {off:.2f}ms",
        )
        for cam, off in peers.items()
    ]
    all_reports = reports + peer_reports
    # Local gates and peer sync must all pass — misaligned peers block recording.
    blocking = [r for r in all_reports if not r.ok]
    return {
        "ok": not blocking,
        "reports": [
            {"name": r.name, "ok": r.ok, "reason": r.reason}
            for r in all_reports
        ],
        "blocking": [{"name": r.name, "reason": r.reason} for r in blocking],
        "peers_online": list(peers.keys()),
    }
