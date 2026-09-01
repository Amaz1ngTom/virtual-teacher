from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_EMOTIONS = {
    "angry",
    "disgust",
    "fear",
    "happy",
    "neutral",
    "sad",
    "surprise",
}


@dataclass
class ReplyPlan:
    reply_text: str
    emotion: str = "neutral"
    speech_rate: float = 1.0
    memory_update: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ReplyPlan":
        emotion = self.emotion if self.emotion in SUPPORTED_EMOTIONS else "neutral"
        speech_rate = min(1.4, max(0.6, float(self.speech_rate)))
        return ReplyPlan(
            reply_text=str(self.reply_text).strip(),
            emotion=emotion,
            speech_rate=speech_rate,
            memory_update=dict(self.memory_update or {}),
        )


@dataclass
class EvaluationPlan:
    correct: bool
    feedback_text: str
    emotion: str = "neutral"
    speech_rate: float = 1.0

    def normalized(self) -> "EvaluationPlan":
        emotion = self.emotion if self.emotion in SUPPORTED_EMOTIONS else "neutral"
        speech_rate = min(1.4, max(0.6, float(self.speech_rate)))
        return EvaluationPlan(
            correct=bool(self.correct),
            feedback_text=str(self.feedback_text).strip(),
            emotion=emotion,
            speech_rate=speech_rate,
        )
