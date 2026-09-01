from __future__ import annotations

import asyncio
import time
import uuid
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import (
    build_course_designer,
    build_float_client,
    build_runtime,
    build_tts,
)
from app.adapters.llm import LLMProviderError, LLMResponseFormatError
from app.asr import LocalASR
from app.asr_api import router as asr_router
from app.config import Settings
from app.conversation_store import SQLiteConversationStore
from app.course_media_cache import CourseMediaCache
from app.course_import import MAX_PDF_BYTES, CourseImportError, preview_pdf_bytes
from app.course_design import (
    CourseDesignError,
    chapter_generation_plan,
    design_chapter_in_batches,
    normalize_course_blueprint,
)
from app.course_import_store import CourseImportStore
from app.embeddings import LocalBGEEmbedder
from app.lessons import (
    get_lesson,
    list_lessons,
    register_published_course,
    unregister_published_course,
)
from app.pipeline_metrics import PipelineMetricsLogger
from app.rag import RAG_BACKEND, TextbookRAGStore, format_retrieval_context
from app.speech_text import prepare_speech_text
from app.text_segmentation import segment_for_avatar


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None
    lesson_id: str = "default"
    synthesize_audio: bool = False
    render_video: bool = False
    lesson_action: Literal[
        "user", "start", "advance", "answer", "question",
        "dynamic_start", "dynamic_advance", "dynamic_stop"
    ] = "user"


class ChatResponse(BaseModel):
    thread_id: str
    reply_text: str
    emotion: str
    speech_rate: float
    profile: dict
    teaching_state: dict | None = None
    audio: dict | None = None
    video_job: dict | None = None
    media_segments: list[dict] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)
    media_error: str | None = None
    sources: list[dict] = Field(default_factory=list)
    retrieval: dict | None = None


class MediaRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    emotion: str = "neutral"
    speech_rate: float = Field(default=1.0, ge=0.6, le=1.4)
    render_video: bool = True


class MediaResponse(BaseModel):
    media_segments: list[dict] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)
    media_error: str | None = None


class ConversationSummary(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    emotion: str | None = None
    created_at: str


class ConversationDetail(BaseModel):
    thread_id: str
    title: str
    lesson_id: str
    created_at: str
    updated_at: str
    teaching_state: dict | None = None
    messages: list[ConversationMessage]


class CourseSourcePage(BaseModel):
    page_number: int = Field(ge=1)
    has_text_layer: bool = True
    text: str = Field(min_length=1, max_length=30_000)


class CourseDesignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    audience: str = Field(default="具备基础数学知识的本科生", min_length=2, max_length=100)
    lesson_count: int = Field(default=2, ge=1, le=4)
    target_minutes: int = Field(default=30, ge=10, le=120)
    pages: list[CourseSourcePage] = Field(min_length=1, max_length=20)


class ChapterDesignRequest(BaseModel):
    audience: str = Field(default="具备基础数学知识的本科生", min_length=2, max_length=100)
    lesson_count: int = Field(default=4, ge=1, le=12)
    target_minutes: int = Field(default=60, ge=10, le=360)


class ChapterRangeUpdate(BaseModel):
    chapter_index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=100)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class ChapterListUpdate(BaseModel):
    chapters: list[ChapterRangeUpdate] = Field(min_length=1, max_length=500)


class CoursePublishRequest(BaseModel):
    blueprint: dict


class RAGSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings.from_env()
    app.state.runtime = build_runtime(app.state.settings)
    app.state.conversations = SQLiteConversationStore(
        app.state.settings.conversation_db
    )
    app.state.tts = None
    app.state.asr = LocalASR(
        app.state.settings.asr_model_dir
        or app.state.settings.project_root.parent / "models" / "sensevoice-small-int8",
        app.state.settings.asr_num_threads,
    )
    app.state.course_designer = None
    app.state.course_imports = CourseImportStore(
        app.state.settings.data_dir / "course-imports"
    )
    app.state.rag = TextbookRAGStore(
        app.state.settings.data_dir / "textbook-rag.sqlite3",
        embedder=LocalBGEEmbedder(
            app.state.settings.rag_embedding_model,
            device=app.state.settings.rag_embedding_device,
            batch_size=app.state.settings.rag_embedding_batch_size,
        ),
    )
    for record in app.state.course_imports.published_course_records():
        try:
            register_published_course(record)
        except (KeyError, TypeError, ValueError):
            continue
    app.state.float_client = None
    app.state.video_download_locks = {}
    app.state.course_media_cache = CourseMediaCache(
        app.state.settings.course_media_cache_dir
    )
    app.state.course_media_jobs = {}
    app.state.pipeline_metrics = PipelineMetricsLogger(
        app.state.settings.project_root / "logs" / "pipeline-metrics.jsonl"
    )
    app.state.logged_float_jobs = set()
    yield
    app.state.conversations.close()
    app.state.runtime.close()


app = FastAPI(title="Virtual Teacher MVP", version="0.1.0", lifespan=lifespan)
app.include_router(asr_router)


def _video_root(settings: Settings) -> Path:
    return (settings.project_root / "outputs" / "video").resolve()


def _validated_video_path(settings: Settings, raw_path: str) -> Path:
    path = Path(raw_path).resolve()
    root = _video_root(settings)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Video is outside output directory") from exc
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise HTTPException(status_code=404, detail="Video file is unavailable")
    return path


def _downloaded_video_path(settings: Settings, job_id: str) -> Path:
    try:
        normalized_job_id = uuid.UUID(job_id).hex
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid FLOAT job id") from exc
    return (_video_root(settings) / f"remote-{normalized_job_id}.mp4").resolve()


def _public_video_job(job) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "video_url": (
            f"/v1/video-jobs/{job.job_id}/media"
            if job.status == "completed" and job.video_path
            else None
        ),
        "elapsed_seconds": job.elapsed_seconds,
        "queue_wait_seconds": job.queue_wait_seconds,
        "total_elapsed_seconds": job.total_elapsed_seconds,
        "error": job.error,
    }


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _record_pipeline_event(request: Request, event: str, **payload) -> None:
    logger = getattr(request.app.state, "pipeline_metrics", None)
    if logger is not None:
        logger.record(event, **payload)


def _wav_duration_seconds(path: Path) -> float:
    """Best-effort duration used only for observability and RTF reporting."""
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getframerate() <= 0:
                return 0.0
            return round(audio.getnframes() / audio.getframerate(), 3)
    except (OSError, EOFError, wave.Error):
        return 0.0


async def _build_media_segments(
    *,
    request: Request,
    text: str,
    emotion: str,
    speech_rate: float,
    synthesize_audio: bool,
    render_video: bool,
    cache_scope: str = "",
) -> tuple[list[dict], dict, str | None]:
    settings = request.app.state.settings
    segment_texts = segment_for_avatar(
        text,
        max_chars=settings.avatar_segment_max_chars,
    )
    media_segments: list[dict] = []
    timings = {
        "segment_count": len(segment_texts),
        "cache_hits": 0,
        "tts_ms": 0.0,
        "float_submit_ms": 0.0,
        "audio_seconds": 0.0,
        "segments": [],
    }
    course_cache = getattr(request.app.state, "course_media_cache", None)

    for index, segment_text in enumerate(segment_texts):
        speech_text = prepare_speech_text(segment_text)
        cache_id = None
        cached_video_url = None
        if render_video and not synthesize_audio and cache_scope and course_cache is not None:
            cache_id = course_cache.make_id(
                scope=cache_scope,
                text=speech_text,
                segment_index=index,
                emotion=emotion,
                speech_rate=speech_rate,
                settings=settings,
            )
            if course_cache.get(cache_id) is not None:
                cached_video_url = f"/v1/course-media/{cache_id}"

        segment_timing = {
            "index": index,
            "cache_hit": bool(cached_video_url),
            "tts_ms": 0.0,
            "float_submit_ms": 0.0,
            "audio_seconds": 0.0,
        }
        if cached_video_url:
            timings["cache_hits"] += 1
            timings["segments"].append(segment_timing)
            media_segments.append(
                {
                    "index": index,
                    "text": segment_text,
                    "speech_text": speech_text,
                    "characters": len(segment_text),
                    "over_soft_limit": len(segment_text) > settings.avatar_segment_max_chars,
                    "audio": None,
                    "audio_duration_seconds": 0.0,
                    "video_job": None,
                    "video_url": cached_video_url,
                    "cache_hit": True,
                }
            )
            continue

        if request.app.state.tts is None:
            request.app.state.tts = build_tts()
        tts_started = time.perf_counter()
        try:
            tts_result = await asyncio.to_thread(
                request.app.state.tts.synthesize,
                speech_text,
                emotion=emotion,
                speech_rate=speech_rate,
            )
        except Exception as exc:
            return media_segments, timings, (
                f"第 {index + 1}/{len(segment_texts)} 段 TTS 生成失败：{exc}。"
                "文字回答已保留，可以只重试语音和视频。"
            )
        segment_timing["tts_ms"] = _elapsed_ms(tts_started)
        duration = _wav_duration_seconds(tts_result.audio_path)
        segment_timing["audio_seconds"] = duration
        timings["tts_ms"] = round(timings["tts_ms"] + segment_timing["tts_ms"], 2)
        timings["audio_seconds"] = round(timings["audio_seconds"] + duration, 3)

        segment_audio = {
            "path": str(tts_result.audio_path),
            "provider": tts_result.provider,
            "model": tts_result.model,
            "voice": tts_result.voice,
            "characters": tts_result.characters,
            "request_id": tts_result.request_id,
        }
        segment_video_job = None
        if render_video:
            if request.app.state.float_client is None:
                request.app.state.float_client = build_float_client(settings)
            submit_started = time.perf_counter()
            try:
                submitted = await asyncio.to_thread(
                    request.app.state.float_client.submit,
                    audio_path=tts_result.audio_path,
                    reference_image=settings.float_reference_image,
                    emotion=emotion,
                )
            except Exception as exc:
                return media_segments, timings, (
                    f"第 {index + 1}/{len(segment_texts)} 段 FLOAT 任务提交失败：{exc}。"
                    "文字和已生成语音已保留，可以只重试媒体。"
                )
            segment_timing["float_submit_ms"] = _elapsed_ms(submit_started)
            timings["float_submit_ms"] = round(
                timings["float_submit_ms"] + segment_timing["float_submit_ms"], 2
            )
            segment_video_job = _public_video_job(submitted)
            if cache_id:
                jobs = getattr(request.app.state, "course_media_jobs", None)
                if jobs is None:
                    jobs = {}
                    request.app.state.course_media_jobs = jobs
                jobs[submitted.job_id] = cache_id

        timings["segments"].append(segment_timing)
        media_segments.append(
            {
                "index": index,
                "text": segment_text,
                "speech_text": speech_text,
                "characters": len(segment_text),
                "over_soft_limit": len(segment_text) > settings.avatar_segment_max_chars,
                "audio": segment_audio,
                "audio_duration_seconds": duration,
                "video_job": segment_video_job,
                "video_url": None,
                "cache_hit": False,
            }
        )
    return media_segments, timings, None


def _teaching_state_payload(result: dict, lesson) -> dict | None:
    if not result.get("lesson_phase"):
        return None
    concept_index = int(result.get("concept_index", 0))
    checkpoint_choices: list[str] = []
    if (
        lesson is not None
        and (
            (
                lesson.mode == "guided"
                and result.get("lesson_phase") == "await_checkpoint"
            )
            or (
                lesson.mode == "interactive"
                and result.get("lesson_phase") == "await_answer"
            )
        )
        and 0 <= concept_index < len(lesson.concepts)
    ):
        checkpoint_choices = list(lesson.concepts[concept_index].choices)
    return {
        "lesson_phase": result["lesson_phase"],
        "concept_index": result.get("concept_index", 0),
        "attempt_count": result.get("attempt_count", 0),
        "score": result.get("score", 0),
        "current_question": result.get("current_question", ""),
        "lesson_mode": (
            "dynamic"
            if str(result.get("lesson_phase", "")).startswith("dynamic_")
            else lesson.mode if lesson is not None else "chat"
        ),
        "section_total": (
            int(result.get("dynamic_section_total", 0))
            if str(result.get("lesson_phase", "")).startswith("dynamic_")
            else len(lesson.concepts) if lesson is not None else 0
        ),
        "dynamic_topic": result.get("dynamic_topic", ""),
        "dynamic_section_index": result.get("dynamic_section_index", 0),
        "checkpoint_choices": checkpoint_choices,
    }


@app.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "llm_mode": request.app.state.runtime.llm.__class__.__name__,
        "phase": 1,
    }


@app.get("/health/float")
async def float_health(request: Request) -> dict:
    if request.app.state.float_client is None:
        request.app.state.float_client = build_float_client(request.app.state.settings)
    try:
        return await asyncio.to_thread(request.app.state.float_client.health)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"FLOAT worker unavailable: {exc}")


@app.get("/v1/users/{user_id}/profile")
def get_profile(user_id: str, request: Request) -> dict:
    return request.app.state.runtime.profiles.get(user_id)


@app.post("/v1/course-imports")
async def create_course_import(
    request: Request,
    filename: str = Query(default="uploaded.pdf", min_length=1, max_length=255),
) -> dict:
    """Persist one full source PDF and inspect its local chapter structure."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="请上传PDF文件")
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF超过150MB，当前暂不支持")
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF超过150MB，当前暂不支持")
    try:
        return await asyncio.to_thread(
            request.app.state.course_imports.create,
            bytes(buffer),
            filename=filename,
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/course-imports/preview")
async def preview_course_pdf(
    request: Request,
    filename: str = Query(default="uploaded.pdf", min_length=1, max_length=255),
    start_page: int = Query(default=1, ge=1),
    end_page: int = Query(default=6, ge=1),
) -> dict:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="请上传PDF文件")
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF超过150MB，第一版暂不支持")
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF超过150MB，第一版暂不支持")
    try:
        return await asyncio.to_thread(
            preview_pdf_bytes,
            bytes(buffer),
            filename=filename,
            start_page=start_page,
            end_page=end_page,
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/course-imports/design")
async def design_course(payload: CourseDesignRequest, request: Request) -> dict:
    """Generate an editable, source-grounded draft; never publish it directly."""
    if request.app.state.course_designer is None:
        try:
            request.app.state.course_designer = build_course_designer(
                request.app.state.settings
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        blueprint = await asyncio.to_thread(
            request.app.state.course_designer.design,
            filename=payload.filename,
            pages=[page.model_dump() for page in payload.pages],
            audience=payload.audience,
            lesson_count=payload.lesson_count,
            target_minutes=payload.target_minutes,
        )
    except CourseDesignError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"课程草稿无法生成或安全恢复：{exc}",
        ) from exc
    except LLMResponseFormatError as exc:
        raise HTTPException(
            status_code=502,
            detail="课程模型返回格式异常，请重试；当前没有发布或保存课程。",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"课程模型暂时不可用：{exc}",
        ) from exc
    return blueprint


@app.get("/v1/course-imports/{import_id}")
def get_course_import(import_id: str, request: Request) -> dict:
    try:
        return request.app.state.course_imports.get(import_id)
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/course-imports/{import_id}/rag/status")
def get_course_rag_status(import_id: str, request: Request) -> dict:
    try:
        request.app.state.course_imports.get(import_id)
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return request.app.state.rag.status(import_id)


@app.post("/v1/course-imports/{import_id}/rag/index")
async def index_course_for_rag(import_id: str, request: Request) -> dict:
    try:
        metadata = request.app.state.course_imports.get(import_id)
        if metadata.get("requires_ocr"):
            raise CourseImportError("这份教材没有可用文字层，请先完成OCR")
        return await asyncio.to_thread(
            request.app.state.rag.index_pdf,
            import_id=import_id,
            source_path=request.app.state.course_imports.source_path(import_id),
            metadata=metadata,
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/course-imports/{import_id}/rag/search")
async def search_course_rag(
    import_id: str, payload: RAGSearchRequest, request: Request
) -> dict:
    try:
        request.app.state.course_imports.get(import_id)
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    results = await asyncio.to_thread(
        request.app.state.rag.search,
        import_id,
        payload.query,
        top_k=payload.top_k,
    )
    status = request.app.state.rag.status(import_id)
    active_backend = results[0]["backend"] if results else status["backend"]
    return {"query": payload.query, "backend": active_backend, "results": results}


@app.put("/v1/course-imports/{import_id}/chapters")
def update_imported_chapters(
    import_id: str,
    payload: ChapterListUpdate,
    request: Request,
) -> dict:
    try:
        return request.app.state.course_imports.replace_chapters(
            import_id,
            [chapter.model_dump() for chapter in payload.chapters],
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/course-imports/{import_id}/chapters/{chapter_index}/preview")
async def preview_imported_chapter(
    import_id: str,
    chapter_index: int,
    request: Request,
    lesson_count: int = Query(default=4, ge=1, le=12),
) -> dict:
    try:
        result = await asyncio.to_thread(
            request.app.state.course_imports.preview_chapter,
            import_id,
            chapter_index,
        )
        result["generation_plan"] = chapter_generation_plan(
            result["pages"], requested_lessons=lesson_count
        )
        return result
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CourseDesignError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/course-imports/{import_id}/chapters/{chapter_index}/draft")
def get_imported_chapter_draft(
    import_id: str,
    chapter_index: int,
    request: Request,
) -> dict:
    try:
        return request.app.state.course_imports.get_chapter_blueprint(
            import_id, chapter_index
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/course-imports/{import_id}/chapters/{chapter_index}/design")
async def design_imported_chapter(
    import_id: str,
    chapter_index: int,
    payload: ChapterDesignRequest,
    request: Request,
) -> dict:
    if request.app.state.course_designer is None:
        try:
            request.app.state.course_designer = build_course_designer(
                request.app.state.settings
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        preview = await asyncio.to_thread(
            request.app.state.course_imports.preview_chapter,
            import_id,
            chapter_index,
        )
        chapter = preview["chapter"]
        blueprint = await asyncio.to_thread(
            design_chapter_in_batches,
            request.app.state.course_designer,
            filename=preview["filename"],
            chapter_title=str(chapter["title"]),
            pages=preview["pages"],
            audience=payload.audience,
            lesson_count=payload.lesson_count,
            target_minutes=payload.target_minutes,
        )
        return await asyncio.to_thread(
            request.app.state.course_imports.save_chapter_blueprint,
            import_id,
            chapter_index,
            blueprint,
        )
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CourseDesignError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"课程草稿无法生成或安全恢复：{exc}",
        ) from exc
    except LLMResponseFormatError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"章节课程模型返回格式异常：{exc}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=f"课程模型暂时不可用：{exc}") from exc


@app.post("/v1/course-imports/{import_id}/chapters/{chapter_index}/publish")
def publish_imported_chapter(
    import_id: str,
    chapter_index: int,
    payload: CoursePublishRequest,
    request: Request,
) -> dict:
    """Validate a reviewed draft and publish it as a deterministic guided course."""
    try:
        draft = request.app.state.course_imports.get_chapter_draft(
            import_id, chapter_index
        )
        chapter = draft["chapter"]
        allowed_pages = set(
            range(int(chapter["start_page"]), int(chapter["end_page"]) + 1)
        )
        raw_lessons = payload.blueprint.get("lessons")
        if not isinstance(raw_lessons, list) or not 1 <= len(raw_lessons) <= 12:
            raise CourseDesignError("课程草稿必须包含1到12个可发布课时")
        normalized = normalize_course_blueprint(
            payload.blueprint,
            allowed_pages=allowed_pages,
            expected_lesson_count=len(raw_lessons),
            default_audience=str(payload.blueprint.get("audience", "学习者")),
        )
        normalized["generator"] = dict(
            payload.blueprint.get("generator", {"provider": "reviewed", "model": "manual"})
        )
        normalized["status"] = "published"
        normalized["grounding"]["human_review_required"] = False
        lesson_id = f"imported-{import_id}-chapter-{chapter_index}"
        saved_blueprint = request.app.state.course_imports.save_chapter_blueprint(
            import_id, chapter_index, normalized
        )
        record = request.app.state.course_imports.publish_chapter_blueprint(
            import_id,
            chapter_index,
            lesson_id=lesson_id,
            blueprint=normalized,
        )
        lesson = register_published_course(record)
        return {
            "course": {
                "lesson_id": lesson.lesson_id,
                "title": lesson.title,
                "mode": lesson.mode,
                "built_in": False,
                "section_total": len(lesson.concepts),
                "published_at": record["published_at"],
            },
            "blueprint": saved_blueprint,
        }
    except CourseImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CourseDesignError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"课程草稿无法发布：{exc}") from exc


@app.delete("/v1/course-imports/{import_id}/chapters/{chapter_index}/publish")
def unpublish_imported_chapter(
    import_id: str,
    chapter_index: int,
    request: Request,
) -> dict:
    """Unpublish one imported course while retaining its reviewed draft."""
    try:
        record = request.app.state.course_imports.unpublish_chapter_blueprint(
            import_id, chapter_index
        )
        lesson_id = str(record["lesson_id"])
        unregister_published_course(lesson_id)
        return {
            "removed": True,
            "lesson_id": lesson_id,
            "draft_preserved": True,
        }
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/courses")
def get_courses() -> list[dict]:
    return list_lessons()


@app.get("/v1/course-projects")
def get_course_projects(request: Request) -> list[dict]:
    """Return saved course drafts and publications from every local textbook."""
    return request.app.state.course_imports.course_projects()


@app.delete("/v1/course-projects/{import_id}/chapters/{chapter_index}")
def delete_course_project(
    import_id: str,
    chapter_index: int,
    request: Request,
) -> dict:
    """Permanently remove generated course records while retaining the textbook."""
    try:
        result = request.app.state.course_imports.delete_course_project(
            import_id, chapter_index
        )
        lesson_id = str(result.get("lesson_id", ""))
        if lesson_id:
            unregister_published_course(lesson_id)
        return result
    except CourseImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/v1/users/{user_id}/conversations",
    response_model=list[ConversationSummary],
)
def list_conversations(user_id: str, request: Request) -> list[dict]:
    return request.app.state.conversations.list_sessions(user_id)


@app.get(
    "/v1/conversations/{thread_id}",
    response_model=ConversationDetail,
)
def get_conversation(thread_id: str, user_id: str, request: Request) -> dict:
    conversation = request.app.state.conversations.get_session(user_id, thread_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="没有找到这段历史问答")
    return conversation


@app.delete("/v1/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: str, request: Request) -> dict:
    conversations = request.app.state.conversations
    conversation = conversations.get_session(user_id, thread_id)
    temporary_deleted = conversations.delete_temporary_thread(user_id, thread_id)
    if conversation is None and not temporary_deleted:
        raise HTTPException(status_code=404, detail="没有找到这个会话")
    try:
        request.app.state.runtime.delete_thread(user_id=user_id, thread_id=thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if conversation is not None:
        conversations.delete_session(user_id, thread_id)
    return {"deleted": True, "thread_id": thread_id}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    request_started = time.perf_counter()
    thread_id = payload.thread_id or uuid.uuid4().hex
    retrieval_results: list[dict] = []
    retrieval_context = ""
    retrieval_info: dict | None = None
    course_imports = getattr(request.app.state, "course_imports", None)
    rag = getattr(request.app.state, "rag", None)
    published_course = (
        course_imports.published_course_record(payload.lesson_id)
        if course_imports is not None
        else None
    )
    if (
        payload.lesson_action == "question"
        and published_course is not None
        and rag is not None
    ):
        import_id = str(published_course["import_id"])
        rag_status = rag.status(import_id)
        if rag_status.get("indexed"):
            retrieval_results = await asyncio.to_thread(
                rag.search,
                import_id,
                payload.text,
                top_k=4,
            )
            retrieval_context = format_retrieval_context(retrieval_results)
        retrieval_info = {
            "used": bool(retrieval_results),
            "indexed": bool(rag_status.get("indexed")),
            "backend": (
                str(
                    retrieval_results[0].get(
                        "backend", rag_status.get("backend", RAG_BACKEND)
                    )
                )
                if retrieval_results
                else str(rag_status.get("backend", RAG_BACKEND))
            ),
            "import_id": import_id,
        }
    graph_started = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            request.app.state.runtime.invoke,
            user_id=payload.user_id,
            thread_id=thread_id,
            lesson_id=payload.lesson_id,
            text=payload.text,
            lesson_action=payload.lesson_action,
            retrieval_context=retrieval_context,
        )
    except LLMResponseFormatError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "语言模型返回格式异常，请重试。"
                "本次未进入语音和视频生成，因此不会产生后续 TTS/FLOAT 消耗。"
            ),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"教学模型暂时不可用，请稍后重试。本次未进入 TTS/FLOAT。{exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    graph_ms = _elapsed_ms(graph_started)
    conversations = getattr(request.app.state, "conversations", None)
    if conversations is not None and payload.lesson_id != "default":
        old_thread_id = conversations.replace_temporary_thread(
            user_id=payload.user_id,
            lesson_id=payload.lesson_id,
            thread_id=thread_id,
        )
        if old_thread_id:
            try:
                request.app.state.runtime.delete_thread(
                    user_id=payload.user_id,
                    thread_id=old_thread_id,
                )
            except ValueError:
                # A registry mismatch must not invalidate the new course turn.
                pass
    audio = None
    media_segments: list[dict] = []
    media_timings: dict = {
        "segment_count": 0,
        "cache_hits": 0,
        "tts_ms": 0.0,
        "float_submit_ms": 0.0,
        "audio_seconds": 0.0,
        "segments": [],
    }
    media_error = None
    if payload.synthesize_audio or payload.render_video:
        cache_scope = str(result.get("media_cache_scope", "")).strip()
        media_segments, media_timings, media_error = await _build_media_segments(
            request=request,
            text=result["response_text"],
            emotion=result["emotion"],
            speech_rate=result["speech_rate"],
            synthesize_audio=payload.synthesize_audio,
            render_video=payload.render_video,
            cache_scope=cache_scope,
        )
        if media_segments:
            audio = media_segments[0]["audio"]
    video_job = next(
        (
            segment["video_job"]
            for segment in media_segments
            if segment["video_job"] is not None
        ),
        None,
    )
    lesson = get_lesson(payload.lesson_id)
    teaching_state = _teaching_state_payload(result, lesson)
    timings = {
        "graph_ms": graph_ms,
        **media_timings,
        "request_ms": _elapsed_ms(request_started),
    }
    response = ChatResponse(
        thread_id=thread_id,
        reply_text=result["response_text"],
        emotion=result["emotion"],
        speech_rate=result["speech_rate"],
        profile=result["profile"],
        teaching_state=teaching_state,
        audio=audio,
        video_job=video_job,
        media_segments=media_segments,
        timings=timings,
        media_error=media_error,
        sources=[
            {
                "page_number": item["page_number"],
                "chapter_title": item["chapter_title"],
                "score": item["score"],
                "snippet": item["text"][:220],
            }
            for item in retrieval_results
        ],
        retrieval=retrieval_info,
    )
    if conversations is not None and payload.lesson_id == "default":
        visible_user_text = (
            payload.text
            if payload.lesson_action in {"user", "question", "answer", "dynamic_start"}
            else None
        )
        conversations.record_turn(
            user_id=payload.user_id,
            thread_id=thread_id,
            user_text=visible_user_text,
            assistant_text=result["response_text"],
            emotion=result["emotion"],
            teaching_state=teaching_state,
        )
    _record_pipeline_event(
        request,
        "chat_response",
        thread_id=thread_id,
        lesson_id=payload.lesson_id,
        lesson_action=payload.lesson_action,
        render_video=payload.render_video,
        media_error=bool(media_error),
        timings=timings,
    )
    return response


@app.post("/v1/media", response_model=MediaResponse)
async def retry_media(payload: MediaRequest, request: Request) -> MediaResponse:
    """Regenerate media from an existing reply without invoking LangGraph/LLM."""
    request_started = time.perf_counter()
    segments, timings, media_error = await _build_media_segments(
        request=request,
        text=payload.text,
        emotion=payload.emotion,
        speech_rate=payload.speech_rate,
        synthesize_audio=False,
        render_video=payload.render_video,
    )
    timings["graph_ms"] = 0.0
    timings["request_ms"] = _elapsed_ms(request_started)
    _record_pipeline_event(
        request,
        "media_retry",
        render_video=payload.render_video,
        media_error=bool(media_error),
        timings=timings,
    )
    return MediaResponse(
        media_segments=segments,
        timings=timings,
        media_error=media_error,
    )


@app.get("/v1/video-jobs/{job_id}")
async def get_video_job(job_id: str, request: Request) -> dict:
    if request.app.state.float_client is None:
        request.app.state.float_client = build_float_client(request.app.state.settings)
    try:
        job = await asyncio.to_thread(request.app.state.float_client.get_job, job_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FLOAT job query failed: {exc}")
    public_job = _public_video_job(job)
    logged_jobs = getattr(request.app.state, "logged_float_jobs", None)
    if logged_jobs is None:
        logged_jobs = set()
        request.app.state.logged_float_jobs = logged_jobs
    if job.status in {"completed", "failed"} and job_id not in logged_jobs:
        logged_jobs.add(job_id)
        _record_pipeline_event(
            request,
            "float_completed",
            job_id=job_id,
            status=job.status,
            queue_wait_seconds=job.queue_wait_seconds,
            inference_seconds=job.elapsed_seconds,
            total_elapsed_seconds=job.total_elapsed_seconds,
            error=bool(job.error),
        )
    return public_job


@app.get("/v1/video-jobs/{job_id}/media")
async def get_video_media(job_id: str, request: Request) -> FileResponse:
    if request.app.state.float_client is None:
        request.app.state.float_client = build_float_client(request.app.state.settings)
    try:
        job = await asyncio.to_thread(request.app.state.float_client.get_job, job_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FLOAT job query failed: {exc}")
    if job.status != "completed" or not job.video_path:
        raise HTTPException(status_code=409, detail="Video is not ready")
    settings = request.app.state.settings
    if settings.float_transfer_mode == "upload":
        path = _downloaded_video_path(settings, job_id)
        locks = getattr(request.app.state, "video_download_locks", None)
        if locks is None:
            locks = {}
            request.app.state.video_download_locks = locks
        download_lock = locks.setdefault(job_id, asyncio.Lock())
        async with download_lock:
            if not path.is_file():
                try:
                    await asyncio.to_thread(
                        request.app.state.float_client.download_video,
                        job_id,
                        path,
                    )
                except Exception as exc:
                    raise HTTPException(
                        status_code=502,
                        detail=f"FLOAT video download failed: {exc}",
                    ) from exc
        path = _validated_video_path(settings, str(path))
    else:
        path = _validated_video_path(settings, job.video_path)
    cache_jobs = getattr(request.app.state, "course_media_jobs", {})
    cache_id = cache_jobs.get(job_id)
    course_cache = getattr(request.app.state, "course_media_cache", None)
    if cache_id and course_cache is not None:
        try:
            course_cache.store(cache_id, path)
        except OSError:
            # A cache write failure must not prevent delivery of a completed
            # FLOAT result. The next request can render it again.
            pass
        else:
            cache_jobs.pop(job_id, None)
    return FileResponse(path, media_type="video/mp4")


@app.get("/v1/course-media/{cache_id}")
def get_course_media(cache_id: str, request: Request) -> FileResponse:
    course_cache = getattr(request.app.state, "course_media_cache", None)
    if course_cache is None:
        raise HTTPException(status_code=404, detail="Course media cache unavailable")
    try:
        path = course_cache.get(cache_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="Course media is unavailable")
    return FileResponse(path, media_type="video/mp4")


@app.get("/v1/avatar/reference")
def get_avatar_reference(request: Request) -> FileResponse:
    path = request.app.state.settings.avatar_reference_image.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Reference image is unavailable")
    return FileResponse(path)


@app.get("/v1/avatar/idle")
def get_avatar_idle_video(request: Request) -> FileResponse:
    path = request.app.state.settings.avatar_idle_video.resolve()
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise HTTPException(status_code=404, detail="Idle video is unavailable")
    return FileResponse(path, media_type="video/mp4")


# In production FastAPI serves the compiled React app from the same port. During
# development Vite proxies /health and /v1 to this API instead.
_frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
