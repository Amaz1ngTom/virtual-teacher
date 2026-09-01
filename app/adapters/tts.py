from __future__ import annotations

import base64
import binascii
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    provider: str
    model: str
    voice: str
    characters: int
    request_id: str = ""


class TTSProvider(Protocol):
    def synthesize(
        self,
        text: str,
        *,
        emotion: str = "neutral",
        speech_rate: float = 1.0,
    ) -> TTSResult: ...


_EMOTION_INSTRUCTIONS = {
    "neutral": "情绪自然、平稳",
    "happy": "语气开心、温暖并带有鼓励感",
    "sad": "语气温和、低沉，但保持关怀",
    "surprise": "语气略带惊喜，表达自然",
    "angry": "语气严肃克制，不要吼叫",
    "fear": "语气谨慎，但不要过度紧张",
    "disgust": "语气克制，避免夸张表现",
}


def build_teacher_instruction(emotion: str, speech_rate: float) -> str:
    """Turn graph control fields into a Qwen3-TTS natural-language instruction."""
    rate = min(1.4, max(0.6, float(speech_rate)))
    if rate <= 0.8:
        rate_text = "语速较慢，每句话之间有清晰停顿"
    elif rate >= 1.2:
        rate_text = "语速稍快，但吐字仍然清晰"
    else:
        rate_text = "语速自然适中"
    emotion_text = _EMOTION_INSTRUCTIONS.get(emotion, _EMOTION_INSTRUCTIONS["neutral"])
    return (
        "使用清晰、亲切、耐心的中文虚拟教师口吻。"
        f"{emotion_text}；{rate_text}。"
        "准确朗读原文，不要添加、删改或解释内容。"
    )


class QwenTTS:
    """HTTP adapter for Alibaba Model Studio Qwen3-TTS.

    The API returns either inline Base64 audio or a temporary OSS URL. Both
    forms are normalized into a persistent local WAV file for FLOAT.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str,
        output_dir: Path,
        optimize_instructions: bool = False,
        timeout_seconds: int = 120,
        session: Any | None = None,
    ):
        if not api_key:
            raise ValueError("Qwen TTS requires a Model Studio API key")
        self.endpoint = (
            base_url.rstrip("/")
            + "/services/aigc/multimodal-generation/generation"
        )
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.output_dir = output_dir
        self.optimize_instructions = optimize_instructions
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(
        self,
        text: str,
        *,
        emotion: str = "neutral",
        speech_rate: float = 1.0,
    ) -> TTSResult:
        text = text.strip()
        if not text:
            raise ValueError("TTS text cannot be empty")
        if len(text) > 600:
            raise ValueError("Qwen3-TTS accepts at most 600 characters per request")

        instruction = build_teacher_instruction(emotion, speech_rate)
        response = self.session.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": {
                    "text": text,
                    "voice": self.voice,
                    "language_type": "Chinese",
                    "instructions": instruction,
                    "optimize_instructions": self.optimize_instructions,
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("status_code", 200)) != 200:
            raise RuntimeError(
                "Qwen TTS failed: "
                + str(payload.get("message") or payload.get("code") or payload)
            )

        audio = (payload.get("output") or {}).get("audio") or {}
        output_path = (self.output_dir / f"tts-{uuid.uuid4().hex}.wav").resolve()
        audio_data = audio.get("data") or ""
        audio_url = audio.get("url") or ""
        if audio_data:
            try:
                output_path.write_bytes(base64.b64decode(audio_data, validate=True))
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("Qwen TTS returned invalid Base64 audio") from exc
        elif audio_url:
            download = self.session.get(audio_url, timeout=self.timeout_seconds)
            download.raise_for_status()
            output_path.write_bytes(download.content)
        else:
            raise RuntimeError("Qwen TTS response did not contain audio data or URL")

        if output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError("Qwen TTS returned an empty audio file")
        usage = payload.get("usage") or {}
        return TTSResult(
            audio_path=output_path,
            provider="qwen",
            model=self.model,
            voice=self.voice,
            characters=int(usage.get("characters", len(text))),
            request_id=str(payload.get("request_id", "")),
        )


class WindowsSapiTTS:
    def __init__(self, output_dir: Path, voice: str):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice

    def synthesize(
        self,
        text: str,
        *,
        emotion: str = "neutral",
        speech_rate: float = 1.0,
    ) -> TTSResult:
        output_path = (self.output_dir / f"tts-{uuid.uuid4().hex}.wav").resolve()
        sapi_rate = round((min(1.4, max(0.6, speech_rate)) - 1.0) * 10)
        script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SelectVoice($env:VT_SAPI_VOICE)
$speaker.Rate = [int]$env:VT_SAPI_RATE
$speaker.SetOutputToWaveFile($env:VT_SAPI_OUTPUT)
$speaker.Speak($env:VT_SAPI_TEXT)
$speaker.Dispose()
""".strip()
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        env = os.environ.copy()
        env.update(
            {
                "VT_SAPI_VOICE": self.voice,
                "VT_SAPI_RATE": str(sapi_rate),
                "VT_SAPI_OUTPUT": str(output_path),
                "VT_SAPI_TEXT": text,
            }
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                "Windows TTS failed: "
                + (result.stderr or result.stdout or "no output file")
            )
        return TTSResult(
            audio_path=output_path,
            provider="windows-sapi",
            model="sapi",
            voice=self.voice,
            characters=len(text),
        )
