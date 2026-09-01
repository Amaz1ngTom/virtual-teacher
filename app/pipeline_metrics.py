from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class PipelineMetricsLogger:
    """Append privacy-light timing events without storing lesson text."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: str, **payload: Any) -> None:
        item = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": event,
            **payload,
        }
        line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
