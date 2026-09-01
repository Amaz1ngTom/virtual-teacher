from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.speech_text import PRONUNCIATION_LEXICON_VERSION


def _path_fingerprint(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        stat = resolved.stat()
    except OSError:
        return {"path": str(resolved), "missing": True}
    return {
        "path": str(resolved),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


class CourseMediaCache:
    """Content-addressed cache for reusable, non-personal course videos."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def make_id(
        self,
        *,
        scope: str,
        text: str,
        segment_index: int,
        emotion: str,
        speech_rate: float,
        settings: Any,
    ) -> str:
        payload = {
            "version": 2,
            "pronunciation_lexicon": PRONUNCIATION_LEXICON_VERSION,
            "scope": scope,
            "text": text,
            "segment_index": segment_index,
            "emotion": emotion,
            "speech_rate": round(float(speech_rate), 3),
            "tts_model": settings.qwen_tts_model,
            "tts_voice": settings.qwen_tts_voice,
            "tts_optimize_instructions": settings.qwen_tts_optimize_instructions,
            "float_no_crop": settings.float_no_crop,
            "reference_image": _path_fingerprint(settings.float_reference_image),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def path_for(self, cache_id: str) -> Path:
        if len(cache_id) != 64 or any(
            character not in "0123456789abcdef" for character in cache_id
        ):
            raise ValueError("Invalid course media cache id")
        return self.root / f"{cache_id}.mp4"

    def get(self, cache_id: str) -> Path | None:
        path = self.path_for(cache_id)
        return path if path.is_file() else None

    def store(self, cache_id: str, source: Path) -> Path:
        source = source.resolve()
        if not source.is_file() or source.suffix.lower() != ".mp4":
            raise FileNotFoundError(f"Course media source is unavailable: {source}")
        destination = self.path_for(cache_id)
        if destination.is_file():
            return destination
        temporary = destination.with_name(
            f".{destination.stem}-{uuid.uuid4().hex}.tmp.mp4"
        )
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
