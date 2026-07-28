"""Keyword natural-language query over soccer event ontology (no LLM required)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


EVENT_KEYWORDS: dict[str, list[str]] = {
    "goal": ["goal"],
    "goals": ["goal"],
    "scored": ["goal"],
    "shot": ["shot"],
    "shots": ["shot"],
    "save": ["save"],
    "saves": ["save"],
    "pass": ["pass"],
    "passes": ["pass"],
    "tackle": ["tackle"],
    "tackles": ["tackle"],
    "dribble": ["dribble"],
    "dribbles": ["dribble"],
    "corner": ["corner"],
    "corners": ["corner"],
    "foul": ["foul"],
    "fouls": ["foul"],
    "free kick": ["free_kick"],
    "free kicks": ["free_kick"],
    "penalty": ["penalty"],
    "penalties": ["penalty"],
    "yellow": ["yellow_card"],
    "yellow card": ["yellow_card"],
    "red": ["red_card"],
    "red card": ["red_card"],
    "cross": ["cross"],
    "crosses": ["cross"],
    "header": ["header"],
    "headers": ["header"],
    "interception": ["interception"],
    "clearance": ["clearance"],
}


@dataclass
class ParsedQuery:
    event_types: list[str] = field(default_factory=list)
    jersey_number: Optional[int] = None
    half: Optional[int] = None  # 1 or 2
    limit: int = 50
    raw: str = ""


def parse_query(text: str) -> ParsedQuery:
    raw = (text or "").strip()
    lowered = raw.lower()
    types: list[str] = []

    # Longer phrases first
    for phrase in sorted(EVENT_KEYWORDS.keys(), key=len, reverse=True):
        if phrase in lowered:
            for event_type in EVENT_KEYWORDS[phrase]:
                if event_type not in types:
                    types.append(event_type)

    jersey = None
    match = re.search(r"#\s*(\d{1,2})\b", lowered)
    if match:
        jersey = int(match.group(1))

    half = None
    if "first half" in lowered or "1st half" in lowered:
        half = 1
    elif "second half" in lowered or "2nd half" in lowered:
        half = 2

    return ParsedQuery(event_types=types, jersey_number=jersey, half=half, raw=raw)


def _event_half(t_start_ms: int, half_ms: int = 45 * 60 * 1000) -> int:
    return 1 if t_start_ms < half_ms else 2


def search_events(events: Iterable[dict[str, Any]], query: str | ParsedQuery) -> list[dict[str, Any]]:
    parsed = query if isinstance(query, ParsedQuery) else parse_query(query)
    results: list[dict[str, Any]] = []
    for event in events:
        etype = str(event.get("type", "")).lower()
        if parsed.event_types and etype not in parsed.event_types:
            continue
        if parsed.jersey_number is not None:
            jersey = event.get("jersey_number")
            if jersey is None:
                payload = event.get("payload") or {}
                jersey = payload.get("jersey_number")
            if jersey != parsed.jersey_number:
                continue
        t_ms = int(event.get("t_start_ms") or event.get("timestamp_ms") or 0)
        if parsed.half is not None and _event_half(t_ms) != parsed.half:
            continue
        results.append(event)
        if len(results) >= parsed.limit:
            break
    return results
