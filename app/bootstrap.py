from __future__ import annotations

from app.adapters.float_renderer import FloatWorkerClient
from app.adapters.llm import QwenTeachingLLM, RuleBasedTeachingLLM
from app.adapters.tts import QwenTTS, TTSProvider, WindowsSapiTTS
from app.config import Settings
from app.course_design import QwenCourseDesigner
from app.graph import TeachingGraphRuntime
from app.profile_store import SQLiteProfileStore


def build_runtime(settings: Settings | None = None) -> TeachingGraphRuntime:
    settings = settings or Settings.from_env()
    if settings.llm_mode == "rule":
        llm = RuleBasedTeachingLLM()
    elif settings.llm_mode == "qwen":
        llm = QwenTeachingLLM(
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
            model=settings.qwen_model,
            debug=settings.llm_debug,
            log_dir=settings.llm_log_dir,
        )
    else:
        raise ValueError(f"Unsupported VT_LLM_MODE: {settings.llm_mode}")

    return TeachingGraphRuntime(
        checkpoint_path=settings.checkpoint_db,
        profiles=SQLiteProfileStore(settings.profile_db),
        llm=llm,
    )


def build_tts(settings: Settings | None = None) -> TTSProvider:
    settings = settings or Settings.from_env()
    if settings.tts_mode == "qwen":
        return QwenTTS(
            base_url=settings.qwen_tts_base_url,
            api_key=settings.qwen_api_key,
            model=settings.qwen_tts_model,
            voice=settings.qwen_tts_voice,
            output_dir=settings.tts_output_dir,
            optimize_instructions=settings.qwen_tts_optimize_instructions,
        )
    if settings.tts_mode == "sapi":
        return WindowsSapiTTS(
            output_dir=settings.tts_output_dir,
            voice=settings.qwen_tts_voice,
        )
    raise ValueError(f"Unsupported VT_TTS_MODE: {settings.tts_mode}")


def build_float_client(settings: Settings | None = None) -> FloatWorkerClient:
    settings = settings or Settings.from_env()
    return FloatWorkerClient(
        settings.float_worker_url,
        timeout_seconds=settings.float_worker_timeout_seconds,
        no_crop=settings.float_no_crop,
        transfer_mode=settings.float_transfer_mode,
    )


def build_course_designer(settings: Settings | None = None) -> QwenCourseDesigner:
    settings = settings or Settings.from_env()
    if not settings.qwen_api_key:
        raise ValueError("课程设计需要配置千问 API Key")
    return QwenCourseDesigner(
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key,
        model=settings.qwen_model,
        debug=settings.llm_debug,
        log_dir=settings.llm_log_dir,
    )
