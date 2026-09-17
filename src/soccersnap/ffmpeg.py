"""Single entry point for the FFmpeg invocations used by capture and stitching."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

H264_OUTPUT_ARGS = ("-c:v", "libx264", "-pix_fmt", "yuv420p")


def run_ffmpeg(args: Sequence[str], *, timeout: float) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True, timeout=timeout)
