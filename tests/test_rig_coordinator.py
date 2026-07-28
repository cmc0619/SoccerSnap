from __future__ import annotations

from pathlib import Path

from soccersnap.protocol.schemas import ConfirmRequest, Checksum
from soccersnap.rig.coordinator import FleetCoordinator
from soccersnap.rig.recorder import RecorderFleet


def test_scheduled_start_and_manifests(tmp_path: Path):
    fleet = RecorderFleet(base_dir=tmp_path, simulate=True)
    coord = FleetCoordinator(fleet)
    sleeps: list[float] = []

    started = coord.start_all("GAME_TEST_001", delay_sec=0.2, sleep_fn=lambda s: sleeps.append(s))
    assert started["success"] is True
    assert started["scheduled_start"]
    assert sleeps and 0.05 <= sleeps[0] <= 0.25
    assert started["cameras"]["CAM_L"]["success"] is True

    stopped = coord.stop_all(duration_sec=2.5)
    assert stopped["stopped"] is True
    assert len(stopped["manifests"]) == 3
    nested = stopped["manifests"][0]
    assert "recording" in nested and "timing" in nested
    assert nested["timing"]["scheduled_start"] is not None

    flat = stopped["flat_manifests"][0]
    req = ConfirmRequest(
        session_id=flat["session_id"],
        camera_id=flat["camera_id"],
        file=flat["file"],
        checksum=Checksum(algo="sha256", value=flat["checksum"]["value"]),
    )
    marked = fleet.confirm(req)
    assert marked.offloaded is True

