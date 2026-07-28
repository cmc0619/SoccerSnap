"""Shared filesystem helpers: containment checks, safe names, disk space."""

from __future__ import annotations

import shutil
from pathlib import Path

_UNSAFE_FRAGMENTS = ("..", "/", "\\")


class UnsafePathError(ValueError):
    """A name or path would escape its intended root."""


def is_safe_name(name: str) -> bool:
    """True when `name` is a single path component with no traversal tricks."""
    if not name or name.startswith("."):
        return False
    return not any(fragment in name for fragment in _UNSAFE_FRAGMENTS)


def require_safe_name(name: str, *, label: str = "name") -> str:
    if not is_safe_name(name):
        raise UnsafePathError(f"Invalid {label}")
    return name


def resolve_within(root: Path, *parts: str | Path) -> Path:
    """Resolve `root/parts...` and refuse results outside the resolved root."""
    base = root.resolve()
    candidate = base.joinpath(*parts).resolve()
    if candidate != base and not candidate.is_relative_to(base):
        raise UnsafePathError(f"Path escapes {base}")
    return candidate


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024**3)
