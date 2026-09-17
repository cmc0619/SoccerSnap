"""UTC time helpers — the wire format is always ISO-8601 with a `Z` suffix."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import overload


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@overload
def iso_utc(value: datetime) -> str: ...


@overload
def iso_utc(value: None) -> None: ...


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def seconds_until(target: datetime) -> float:
    """Seconds from now until `target` (negative when already past)."""
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return (target - utcnow()).total_seconds()
