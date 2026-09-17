from __future__ import annotations

from pathlib import Path

from soccersnap.ffmpeg import H264_OUTPUT_ARGS, run_ffmpeg


def stitch_hstack(camera_paths: list[Path], output: Path) -> Path:
    """Stitch L/C/R into a single panorama via FFmpeg hstack."""
    if len(camera_paths) < 2:
        raise ValueError("Need at least two camera clips to stitch")
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    for path in camera_paths:
        inputs.extend(["-i", str(path)])
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            f"hstack=inputs={len(camera_paths)}",
            *H264_OUTPUT_ARGS,
            "-an",
            str(output),
        ],
        timeout=600,
    )
    return output
