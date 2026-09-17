from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FramingQuality(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    PARTIAL = "partial"
    NO_FIELD = "no_field"


@dataclass(slots=True)
class FramingResult:
    quality: FramingQuality
    score: float
    message: str
    tone_hz: int

    def as_dict(self) -> dict:
        return {
            "quality": self.quality.value,
            "score": self.score,
            "message": self.message,
            "tone_hz": self.tone_hz,
        }


# Deterministic simulated framing per camera for demo/preflight.
_SIM_SCORES = {
    "CAM_L": 0.91,
    "CAM_C": 0.96,
    "CAM_R": 0.88,
}


def score_to_quality(score: float) -> FramingResult:
    if score >= 0.9:
        return FramingResult(FramingQuality.EXCELLENT, score, "Field framed cleanly", 880)
    if score >= 0.75:
        return FramingResult(FramingQuality.GOOD, score, "Good framing — minor tilt", 740)
    if score >= 0.4:
        return FramingResult(FramingQuality.PARTIAL, score, "Partial field visible", 520)
    return FramingResult(FramingQuality.NO_FIELD, score, "No field detected — reframe", 320)


def assess_framing(camera_id: str, *, simulate: bool = True, score: float | None = None) -> FramingResult:
    value = score if score is not None else _SIM_SCORES.get(camera_id, 0.8 if simulate else 0.0)
    return score_to_quality(value)
