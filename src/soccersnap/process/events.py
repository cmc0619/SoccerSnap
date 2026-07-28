from __future__ import annotations

"""Deterministic demo event detector — soccer ontology without requiring YOLO."""


def detect_demo_events(duration_sec: float) -> list[dict]:
    duration_ms = int(max(duration_sec, 3.0) * 1000)
    # Spread a believable set of events across the clip / match timeline.
    catalog = [
        ("pass", 0.08, 7, "Outlet pass from #7"),
        ("shot", 0.18, 9, "Shot from #9"),
        ("save", 0.20, 1, "Keeper save"),
        ("corner", 0.28, None, "Corner kick"),
        ("goal", 0.35, 9, "Goal — #9"),
        ("tackle", 0.42, 4, "Tackle by #4"),
        ("dribble", 0.55, 11, "Dribble by #11"),
        ("cross", 0.62, 7, "Cross from #7"),
        ("header", 0.64, 9, "Header by #9"),
        ("foul", 0.72, 6, "Foul on #6"),
        ("free_kick", 0.78, 10, "Free kick #10"),
        ("pass", 0.88, 8, "Through ball #8"),
        ("shot", 0.92, 9, "Late shot #9"),
        ("save", 0.94, 1, "Late save"),
    ]
    events = []
    for etype, frac, jersey, label in catalog:
        start = int(duration_ms * frac)
        end = min(duration_ms, start + 2500)
        events.append(
            {
                "type": etype,
                "t_start_ms": start,
                "t_end_ms": end,
                "confidence": 0.82,
                "jersey_number": jersey,
                "label": label,
                "payload": {"jersey_number": jersey, "source": "demo-detector"},
            }
        )
    return events
