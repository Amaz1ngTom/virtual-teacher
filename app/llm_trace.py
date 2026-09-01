from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class LLMTraceWriter:
    """Write full local LLM request/response traces without credentials."""

    def __init__(self, enabled: bool, directory: Path):
        self.enabled = enabled
        self.directory = directory
        self._lock = threading.Lock()
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> Path | None:
        if not self.enabled:
            return None
        path = self.directory / f"llm-trace-{datetime.now():%Y%m%d}.jsonl"
        safe_record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            **record,
        }
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_record, ensure_ascii=False) + "\n")
        print(f"[LLM trace] {path}", file=sys.stderr)
        return path
