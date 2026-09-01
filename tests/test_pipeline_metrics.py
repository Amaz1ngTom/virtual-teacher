from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.pipeline_metrics import PipelineMetricsLogger


class PipelineMetricsLoggerTests(unittest.TestCase):
    def test_records_timing_without_lesson_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipeline.jsonl"
            logger = PipelineMetricsLogger(path)
            logger.record(
                "chat_response",
                thread_id="thread-1",
                timings={"graph_ms": 12.5},
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "chat_response")
            self.assertEqual(payload["timings"]["graph_ms"], 12.5)
            self.assertNotIn("text", payload)


if __name__ == "__main__":
    unittest.main()
