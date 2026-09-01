"""Lazy, local-only CPU ASR. Uploaded audio stays in memory, not in logs or files."""
from __future__ import annotations

import importlib.util
import io
import re
import threading
import time
import wave
from pathlib import Path

import numpy as np

MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_AUDIO_SECONDS = 60


class ASRError(Exception):
    status_code = 400


class ASRUnavailable(ASRError):
    status_code = 503


class ASRBusy(ASRError):
    status_code = 409


def read_pcm_wav(data: bytes) -> tuple[np.ndarray, int]:
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ASRError("录音为空或超过6MB，请重新录制。")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            rate, frames = audio.getframerate(), audio.getnframes()
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
                raise ASRError("录音需要使用单声道16位PCM WAV格式。")
            if not 8000 <= rate <= 48000:
                raise ASRError("录音采样率需要在8000到48000Hz之间。")
            if not 0.25 <= frames / rate <= MAX_AUDIO_SECONDS:
                raise ASRError("请录制0.25到60秒的语音。")
            raw = audio.readframes(frames)
            if len(raw) != frames * 2:
                raise ASRError("录音数据不完整，请重新录制。")
    except (wave.Error, EOFError, ValueError) as exc:
        raise ASRError("无法读取录音，请使用网页麦克风重新录制。") from exc
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0, rate


class LocalASR:
    def __init__(self, model_dir: Path, num_threads: int = 2):
        self.model_dir = model_dir
        self.num_threads = max(1, min(4, num_threads))
        self._recognizer = None
        self._lock = threading.Lock()

    def status(self) -> dict:
        installed = importlib.util.find_spec("sherpa_onnx") is not None
        files_ready = all((self.model_dir / name).is_file() for name in ("model.int8.onnx", "tokens.txt"))
        available = installed and files_ready
        message = "本地CPU识别 · 首次使用加载模型 · 不自动发送"
        if not installed:
            message = "未安装ASR依赖，请在Web环境安装 requirements-asr.txt。"
        elif not files_ready:
            message = "未找到ASR模型，请运行 scripts/maintenance/download_asr_model.py。"
        return {
            "available": available, "loaded": self._recognizer is not None,
            "busy": self._lock.locked(), "model": "sensevoice-small-int8",
            "device": "cpu", "max_seconds": MAX_AUDIO_SECONDS, "message": message,
        }

    def _load(self):
        if self._recognizer is None:
            status = self.status()
            if not status["available"]:
                raise ASRUnavailable(status["message"])
            import sherpa_onnx

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(self.model_dir / "model.int8.onnx"),
                tokens=str(self.model_dir / "tokens.txt"),
                num_threads=self.num_threads, provider="cpu",
                language="auto", use_itn=True, debug=False,
            )
        return self._recognizer

    def transcribe(self, data: bytes) -> dict:
        samples, rate = read_pcm_wav(data)
        # Do not queue recordings behind another tab or create duplicate models.
        if not self._lock.acquire(blocking=False):
            raise ASRBusy("本地语音识别正在处理另一段录音，请稍后重试。")
        started = time.perf_counter()
        try:
            text, language = "", ""
            # Exact/near silence should never hallucinate text or load the model.
            if float(np.sqrt(np.mean(samples * samples))) >= 0.0003:
                recognizer = self._load()
                stream = recognizer.create_stream()
                # sherpa-onnx internally resamples if the browser uses 44.1/48 kHz.
                stream.accept_waveform(rate, samples)
                recognizer.decode_stream(stream)
                text = re.sub(r"<\|[^|]*\|>", "", stream.result.text).strip()
                language = getattr(stream.result, "lang", "")
            return {
                "text": text, "language": language, "model": "sensevoice-small-int8",
                "device": "cpu", "audio_seconds": round(len(samples) / rate, 3),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except ASRError:
            raise
        except Exception as exc:
            raise ASRUnavailable("本地识别失败，请检查ASR依赖和模型文件，或重试较短录音。") from exc
        finally:
            self._lock.release()
