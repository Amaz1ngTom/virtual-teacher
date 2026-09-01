from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretty-print local LLM traces")
    parser.add_argument("--last", type=int, default=1, help="number of calls to show")
    parser.add_argument("--file", type=Path, help="specific JSONL trace file")
    args = parser.parse_args()
    if args.last < 1:
        parser.error("--last must be at least 1")

    if args.file:
        path = args.file.resolve()
    else:
        log_dir = Settings.from_env().llm_log_dir
        candidates = sorted(log_dir.glob("llm-trace-*.jsonl"))
        if not candidates:
            raise SystemExit(f"No trace files found in {log_dir}")
        path = candidates[-1]

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    records = [json.loads(line) for line in lines[-args.last :]]
    print(f"Trace file: {path}")
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
