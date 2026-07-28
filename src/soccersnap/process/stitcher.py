from __future__ import annotations

import subprocess
from pathlib import Path


def stitch_hstack(camera_paths: list[Path], output: Path) -> Path:
    """Stitch L/C/R into a single panorama via FFmpeg hstack."""
    if len(camera_paths) < 2:
        raise ValueError("Need at least two camera clips to stitch")
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    for path in camera_paths:
        inputs.extend(["-i", str(path)])
    n = len(camera_paths)
    filter_complex = f"hstack=inputs={n}"
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    return output
