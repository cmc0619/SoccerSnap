"""FFmpeg invocation that preserves failure detail instead of dropping stderr."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

STDERR_TAIL_CHARS = 800


class FFmpegError(Exception):
    """FFmpeg is unavailable, timed out, or exited non-zero."""


def _stderr_tail(stderr: bytes | str | None) -> str:
    if not stderr:
        return "no stderr output"
    text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
    text = text.strip()
    return text[-STDERR_TAIL_CHARS:] if len(text) > STDERR_TAIL_CHARS else text


def run_ffmpeg(cmd: list[str], *, timeout: float, context: str) -> subprocess.CompletedProcess:
    """Run an FFmpeg command, raising FFmpegError with the captured stderr tail."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise FFmpegError(f"{context}: ffmpeg executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        logger.error("%s: ffmpeg timed out after %ss", context, timeout)
        raise FFmpegError(f"{context}: ffmpeg timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = _stderr_tail(exc.stderr)
        logger.error("%s: ffmpeg exited %s: %s", context, exc.returncode, detail)
        raise FFmpegError(f"{context}: ffmpeg exited {exc.returncode}: {detail}") from exc
