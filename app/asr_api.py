from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.asr import ASRError, MAX_AUDIO_BYTES

router = APIRouter(prefix="/v1/asr", tags=["local-asr"])


@router.get("/status")
def asr_status(request: Request) -> dict:
    return request.app.state.asr.status()


@router.post("/transcribe")
async def transcribe_audio(request: Request) -> dict:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type not in {"audio/wav", "audio/x-wav", "audio/wave"}:
        raise HTTPException(415, "请上传网页录制的WAV语音。")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "录音超过6MB，请缩短录音后重试。")
        data.extend(chunk)
    try:
        # No LangGraph, LLM, TTS, FLOAT, transcript logging or disk writes here.
        return await asyncio.to_thread(request.app.state.asr.transcribe, bytes(data))
    except ASRError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
