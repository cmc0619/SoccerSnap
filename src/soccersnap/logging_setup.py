"""Process-wide logging configuration so swallowed failures leave a trace."""

from __future__ import annotations

import logging

from soccersnap.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Attach a stderr handler to the soccersnap logger tree (idempotent)."""
    resolved = (level or settings.log_level).upper()
    logger = logging.getLogger("soccersnap")
    logger.setLevel(resolved)
    if not any(getattr(h, "_soccersnap", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        handler._soccersnap = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
