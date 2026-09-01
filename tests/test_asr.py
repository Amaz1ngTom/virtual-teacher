from __future__ import annotations

import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.asr import ASRBusy, ASRError, ASRUnavailable, LocalASR, MAX_AUDIO_BYTES, read_pcm_wav
from app.asr_api import router


def wav_bytes(seconds=1.0, rate=16000, channels=1, width=2, silence=False):
    frames = int(seconds * rate)
    samples = np.zeros(frames, dtype="<i2") if silence else (
        np.sin(np.arange(frames) * 440 * 2 * np.pi / rate) * 8000
    ).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes() * channels)
    return output.getvalue()


class ASRAudioTests(unittest.TestCase):
    def test_reads_pcm_and_preserves_browser_sample_rate(self):
        for rate in (16000, 24000, 44100, 48000):
            samples, actual_rate = read_pcm_wav(wav_bytes(rate=rate))
            self.assertEqual(actual_rate, rate)
            self.assertEqual(len(samples), rate)
            self.assertEqual(samples.dtype, np.float32)
            self.assertLessEqual(float(np.max(np.abs(samples))), 1)

    def test_invalid_or_truncated_audio_rejected(self):
        for data in (b"", b"not audio", wav_bytes()[:-32], b"x" * (MAX_AUDIO_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ASRError):
                read_pcm_wav(data)

    def test_duration_channels_width_and_rate_limits(self):
        for kwargs in ({"seconds": 0.1}, {"seconds": 61}, {"channels": 2}, {"width": 1}, {"rate": 96000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ASRError):
                read_pcm_wav(wav_bytes(**kwargs))

    def test_silence_does_not_load_model_or_hallucinate(self):
        asr = LocalASR(Path("missing-model"))
        with patch.object(asr, "_load", side_effect=AssertionError("must not load")):
            result = asr.transcribe(wav_bytes(silence=True))
        self.assertEqual(result["text"], "")
        self.assertEqual(result["device"], "cpu")

    def test_missing_dependencies_report_unavailable_without_loading(self):
        asr = LocalASR(Path("missing-model"))
        with patch("app.asr.importlib.util.find_spec", return_value=None):
            self.assertFalse(asr.status()["available"])
            self.assertFalse(asr.status()["loaded"])
            with self.assertRaises(ASRUnavailable):
                asr.transcribe(wav_bytes())
        self.assertFalse(asr._lock.locked())

    def test_loaded_model_reused_and_special_tags_removed(self):
        asr = LocalASR(Path("unused"))
        stream = Mock(result=SimpleNamespace(text="<|zh|><|NEUTRAL|>你好，Python。", lang="<|zh|>"))
        recognizer = Mock()
        recognizer.create_stream.return_value = stream
        asr._recognizer = recognizer
        for _ in range(2):
            result = asr.transcribe(wav_bytes())
            self.assertEqual(result["text"], "你好，Python。")
        self.assertEqual(recognizer.decode_stream.call_count, 2)

    def test_concurrent_recording_is_rejected_instead_of_queued(self):
        asr = LocalASR(Path("unused"))
        asr._lock.acquire()
        try:
            with self.assertRaises(ASRBusy):
                asr.transcribe(wav_bytes())
        finally:
            asr._lock.release()

    def test_inference_error_releases_lock(self):
        asr = LocalASR(Path("unused"))
        with patch.object(asr, "_load", side_effect=RuntimeError("internal path")):
            with self.assertRaises(ASRUnavailable) as raised:
                asr.transcribe(wav_bytes())
        self.assertNotIn("internal path", str(raised.exception))
        self.assertFalse(asr._lock.locked())

    def test_runtime_is_cpu_only_and_loads_lazily(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.int8.onnx").touch()
            (root / "tokens.txt").touch()
            fake = Mock()
            with patch("app.asr.importlib.util.find_spec", return_value=object()), patch.dict("sys.modules", {"sherpa_onnx": fake}):
                asr = LocalASR(root, num_threads=2)
                self.assertTrue(asr.status()["available"])
                fake.OfflineRecognizer.from_sense_voice.assert_not_called()
                first = asr._load()
                self.assertIs(asr._load(), first)
                args = fake.OfflineRecognizer.from_sense_voice.call_args.kwargs
                self.assertEqual(args["provider"], "cpu")
                self.assertEqual(args["num_threads"], 2)
                self.assertTrue(args["use_itn"])


class ASRAPITests(unittest.TestCase):
    def setUp(self):
        application = FastAPI()
        application.include_router(router)
        # No LLM/TTS/runtime exists: ASR must work independently of them.
        self.asr = LocalASR(Path("unused"))
        application.state.asr = self.asr
        self.client = TestClient(application)

    def tearDown(self):
        self.client.close()

    def test_status_does_not_load_model(self):
        with patch.object(self.asr, "_load", side_effect=AssertionError("no load")):
            response = self.client.get("/v1/asr/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["loaded"])

    def test_wav_request_returns_text_without_other_services(self):
        with patch.object(self.asr, "transcribe", return_value={"text": "学习变量", "device": "cpu"}) as decode:
            response = self.client.post("/v1/asr/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "学习变量")
        decode.assert_called_once()

    def test_rejects_large_upload_before_asr(self):
        with patch.object(self.asr, "transcribe", side_effect=AssertionError("not called")):
            response = self.client.post("/v1/asr/transcribe", content=b"x" * (MAX_AUDIO_BYTES + 1), headers={"Content-Type": "audio/wav"})
        self.assertEqual(response.status_code, 413)

    def test_rejects_wrong_format(self):
        response = self.client.post("/v1/asr/transcribe", content=b"webm", headers={"Content-Type": "audio/webm"})
        self.assertEqual(response.status_code, 415)

    def test_unavailable_busy_and_bad_audio_have_clear_status(self):
        for error, code in ((ASRUnavailable("模型未安装"), 503), (ASRBusy("识别中"), 409), (ASRError("格式错误"), 400)):
            with patch.object(self.asr, "transcribe", side_effect=error):
                response = self.client.post("/v1/asr/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
            self.assertEqual(response.status_code, code)
            self.assertEqual(response.json()["detail"], str(error))


if __name__ == "__main__":
    unittest.main()
