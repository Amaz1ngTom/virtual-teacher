from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.adapters.float_renderer import FloatJobResult
from app.adapters.llm import LLMResponseFormatError
from app.adapters.tts import TTSResult
from app.api import ChatRequest, MediaRequest, chat, get_video_media, retry_media
from app.course_media_cache import CourseMediaCache
from app.conversation_store import SQLiteConversationStore


class _FakeRuntime:
    def invoke(self, **_kwargs):
        return {
            "response_text": "第一段内容比较完整。第二段内容也很完整。第三段提出问题！",
            "emotion": "happy",
            "speech_rate": 1.0,
            "profile": {},
        }


class _FakeTTS:
    def __init__(self):
        self.texts: list[str] = []

    def synthesize(self, text: str, **_kwargs) -> TTSResult:
        self.texts.append(text)
        return TTSResult(
            audio_path=Path(f"segment-{len(self.texts)}.wav"),
            provider="fake",
            model="fake-tts",
            voice="teacher",
            characters=len(text),
        )


class _FakeFloatClient:
    def __init__(self):
        self.audio_paths: list[Path] = []

    def submit(self, *, audio_path: Path, **_kwargs) -> FloatJobResult:
        self.audio_paths.append(audio_path)
        return FloatJobResult(
            job_id=f"job-{len(self.audio_paths)}",
            status="queued",
        )


class ApiMediaPipelineTests(unittest.TestCase):
    def test_free_chat_response_is_saved_for_visible_history(self):
        with tempfile.TemporaryDirectory() as directory:
            conversations = SQLiteConversationStore(
                Path(directory) / "conversations.sqlite3"
            )
            state = SimpleNamespace(
                runtime=_FakeRuntime(),
                conversations=conversations,
                tts=None,
                float_client=None,
            )
            request = SimpleNamespace(app=SimpleNamespace(state=state))
            try:
                response = asyncio.run(
                    chat(
                        ChatRequest(
                            user_id="history-user",
                            thread_id="history-thread",
                            text="高等数学",
                        ),
                        request,
                    )
                )
                restored = conversations.get_session(
                    "history-user", response.thread_id
                )
                self.assertIsNotNone(restored)
                self.assertEqual(restored["title"], "高等数学")
                self.assertEqual(
                    [message["role"] for message in restored["messages"]],
                    ["user", "assistant"],
                )
            finally:
                conversations.close()

    def test_published_course_question_injects_rag_and_returns_sources(self):
        class CapturingRuntime(_FakeRuntime):
            kwargs = None

            def invoke(self, **kwargs):
                self.kwargs = kwargs
                return super().invoke(**kwargs)

        class FakeImports:
            @staticmethod
            def published_course_record(lesson_id):
                if lesson_id == "imported-demo-chapter-1":
                    return {"lesson_id": lesson_id, "import_id": "demo"}
                return None

        class FakeRAG:
            @staticmethod
            def status(_import_id):
                return {"indexed": True}

            @staticmethod
            def search(_import_id, _query, *, top_k):
                self.assertEqual(top_k, 4)
                return [{
                    "page_number": 23,
                    "chapter_title": "模型评估与选择",
                    "score": 8.5,
                    "text": "过拟合会导致泛化性能下降。",
                }]

        runtime = CapturingRuntime()
        state = SimpleNamespace(
            runtime=runtime,
            course_imports=FakeImports(),
            rag=FakeRAG(),
            conversations=None,
            tts=None,
            float_client=None,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        response = asyncio.run(chat(ChatRequest(
            user_id="test",
            lesson_id="imported-demo-chapter-1",
            lesson_action="question",
            text="什么是过拟合？",
        ), request))

        self.assertIn("PDF第23页", runtime.kwargs["retrieval_context"])
        self.assertTrue(response.retrieval["used"])
        self.assertEqual(response.sources[0]["page_number"], 23)

    def test_llm_format_failure_returns_502_before_tts(self):
        class BrokenRuntime:
            def invoke(self, **_kwargs):
                raise LLMResponseFormatError("bad shape")

        state = SimpleNamespace(runtime=BrokenRuntime(), tts=None)
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        with self.assertRaisesRegex(Exception, "语言模型返回格式异常") as caught:
            asyncio.run(chat(ChatRequest(user_id="test", text="讲一下函数"), request))

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIsNone(state.tts)

    @staticmethod
    def _cache_settings(directory: str | Path):
        return SimpleNamespace(
            avatar_segment_max_chars=110,
            qwen_tts_model="fake-tts",
            qwen_tts_voice="teacher",
            qwen_tts_optimize_instructions=False,
            float_no_crop=False,
            float_reference_image=Path(directory) / "teacher.png",
        )

    def test_guided_course_cache_hit_skips_tts_and_float(self):
        text = "这是一段完全固定的课程讲稿。"

        class CachedRuntime:
            def invoke(self, **_kwargs):
                return {
                    "response_text": text,
                    "emotion": "neutral",
                    "speech_rate": 1.0,
                    "profile": {},
                    "lesson_phase": "lecture",
                    "concept_index": 0,
                    "attempt_count": 0,
                    "score": 0,
                    "current_question": "",
                    "media_cache_scope": "python-lecture/section-1",
                }

        with tempfile.TemporaryDirectory() as directory:
            settings = self._cache_settings(directory)
            settings.float_reference_image.write_bytes(b"teacher")
            cache = CourseMediaCache(Path(directory) / "course-media")
            cache_id = cache.make_id(
                scope="python-lecture/section-1",
                text=text,
                segment_index=0,
                emotion="neutral",
                speech_rate=1.0,
                settings=settings,
            )
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"cached-course-video")
            cache.store(cache_id, source)
            state = SimpleNamespace(
                runtime=CachedRuntime(),
                tts=None,
                float_client=None,
                course_media_cache=cache,
                course_media_jobs={},
                settings=settings,
            )
            request = SimpleNamespace(app=SimpleNamespace(state=state))

            response = asyncio.run(
                chat(
                    ChatRequest(
                        user_id="cached-user",
                        text="开始课程",
                        lesson_id="python-lecture",
                        lesson_action="start",
                        render_video=True,
                    ),
                    request,
                )
            )

            self.assertIsNone(state.tts)
            self.assertIsNone(state.float_client)
            self.assertTrue(response.media_segments[0]["cache_hit"])
            self.assertEqual(
                response.media_segments[0]["video_url"],
                f"/v1/course-media/{cache_id}",
            )

    def test_guided_checkpoint_response_exposes_choice_buttons(self):
        class GuidedRuntime:
            def invoke(self, **_kwargs):
                return {
                    "response_text": "讲解完成。检查题：哪个变量名合法？",
                    "emotion": "neutral",
                    "speech_rate": 1.0,
                    "profile": {},
                    "lesson_phase": "await_checkpoint",
                    "concept_index": 1,
                    "attempt_count": 0,
                    "score": 0,
                    "current_question": "下面哪个是合法的Python变量名：2name、user_name、class？",
                }

        state = SimpleNamespace(
            runtime=GuidedRuntime(),
            tts=None,
            float_client=None,
            settings=SimpleNamespace(avatar_segment_max_chars=110),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        response = asyncio.run(
            chat(
                ChatRequest(
                    user_id="guided-user",
                    text="自动进入下一讲",
                    lesson_id="python-lecture",
                    lesson_action="advance",
                ),
                request,
            )
        )

        self.assertEqual(response.teaching_state["lesson_mode"], "guided")
        self.assertEqual(
            response.teaching_state["checkpoint_choices"],
            ["2name", "user_name", "class"],
        )

    def test_interactive_question_exposes_choice_buttons(self):
        class InteractiveRuntime:
            def invoke(self, **_kwargs):
                return {
                    "response_text": "请选择合法的变量名。",
                    "emotion": "neutral",
                    "speech_rate": 1.0,
                    "profile": {},
                    "lesson_phase": "await_answer",
                    "concept_index": 1,
                    "attempt_count": 0,
                    "score": 1,
                    "current_question": "下面哪个是合法的Python变量名？",
                }

        state = SimpleNamespace(
            runtime=InteractiveRuntime(),
            tts=None,
            float_client=None,
            settings=SimpleNamespace(avatar_segment_max_chars=110),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        response = asyncio.run(
            chat(
                ChatRequest(
                    user_id="interactive-user",
                    text="开始课程",
                    lesson_id="python-basics",
                    lesson_action="start",
                ),
                request,
            )
        )

        self.assertEqual(
            response.teaching_state["checkpoint_choices"],
            ["2name", "user_name", "class"],
        )

    def test_chat_synthesizes_and_queues_each_text_segment(self):
        tts = _FakeTTS()
        float_client = _FakeFloatClient()
        state = SimpleNamespace(
            runtime=_FakeRuntime(),
            tts=tts,
            float_client=float_client,
            settings=SimpleNamespace(
                avatar_segment_max_chars=22,
                float_reference_image=Path("teacher.png"),
            ),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        response = asyncio.run(
            chat(
                ChatRequest(user_id="test", text="请开始", render_video=True),
                request,
            )
        )

        self.assertEqual(len(response.media_segments), 2)
        self.assertEqual(tts.texts, [
            "第一段内容比较完整。第二段内容也很完整。",
            "第三段提出问题！",
        ])
        self.assertEqual(len(float_client.audio_paths), 2)
        self.assertEqual(response.video_job["job_id"], "job-1")
        self.assertEqual(
            [item["video_job"]["job_id"] for item in response.media_segments],
            ["job-1", "job-2"],
        )
        self.assertEqual(response.timings["segment_count"], 2)
        self.assertEqual(response.timings["cache_hits"], 0)
        self.assertIn("graph_ms", response.timings)
        self.assertIn("request_ms", response.timings)

    def test_media_failure_preserves_text_and_can_retry_without_llm(self):
        class BrokenTTS:
            def synthesize(self, *_args, **_kwargs):
                raise RuntimeError("temporary TTS outage")

        state = SimpleNamespace(
            runtime=_FakeRuntime(),
            tts=BrokenTTS(),
            float_client=None,
            settings=SimpleNamespace(
                avatar_segment_max_chars=110,
                float_reference_image=Path("teacher.png"),
            ),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        response = asyncio.run(
            chat(
                ChatRequest(user_id="media-user", text="开始", render_video=True),
                request,
            )
        )
        self.assertEqual(response.reply_text, _FakeRuntime().invoke()["response_text"])
        self.assertIn("只重试语音和视频", response.media_error)
        self.assertEqual(response.media_segments, [])

        state.tts = _FakeTTS()
        state.float_client = _FakeFloatClient()
        retried = asyncio.run(
            retry_media(
                MediaRequest(
                    text=response.reply_text,
                    emotion=response.emotion,
                    speech_rate=response.speech_rate,
                ),
                request,
            )
        )
        self.assertIsNone(retried.media_error)
        self.assertGreater(len(retried.media_segments), 0)
        self.assertEqual(retried.timings["graph_ms"], 0.0)

    def test_tts_receives_pronunciation_text_while_response_keeps_code(self):
        class PronunciationRuntime:
            def invoke(self, **_kwargs):
                return {
                    "response_text": "结果是 str，合法变量名是 user_name。",
                    "emotion": "neutral",
                    "speech_rate": 1.0,
                    "profile": {},
                }

        tts = _FakeTTS()
        state = SimpleNamespace(
            runtime=PronunciationRuntime(),
            tts=tts,
            float_client=None,
            settings=SimpleNamespace(avatar_segment_max_chars=110),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        response = asyncio.run(
            chat(
                ChatRequest(
                    user_id="pronunciation-user",
                    text="回答",
                    synthesize_audio=True,
                ),
                request,
            )
        )

        self.assertEqual(response.reply_text, "结果是 str，合法变量名是 user_name。")
        self.assertEqual(
            tts.texts,
            ["结果是 string，合法变量名是 user，下划线，name。"],
        )
        self.assertEqual(
            response.media_segments[0]["speech_text"],
            "结果是 string，合法变量名是 user，下划线，name。",
        )

    def test_remote_media_is_downloaded_into_local_video_cache(self):
        job_id = "63e07d52f1d64ee2939a576d42d7794d"

        class DownloadClient:
            downloads = 0

            def get_job(self, requested_job_id):
                self.requested_job_id = requested_job_id
                return FloatJobResult(
                    job_id=requested_job_id,
                    status="completed",
                    video_path="/workspace/virtual-teacher-worker/outputs/video.mp4",
                )

            def download_video(self, requested_job_id, output_path):
                self.downloads += 1
                self.downloaded_job_id = requested_job_id
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"remote-video")
                return output_path

        with tempfile.TemporaryDirectory() as directory:
            client = DownloadClient()
            settings = SimpleNamespace(
                project_root=Path(directory),
                float_transfer_mode="upload",
            )
            state = SimpleNamespace(float_client=client, settings=settings)
            request = SimpleNamespace(app=SimpleNamespace(state=state))

            response = asyncio.run(get_video_media(job_id, request))

            self.assertEqual(Path(response.path).read_bytes(), b"remote-video")
            self.assertEqual(client.downloads, 1)
            self.assertEqual(client.downloaded_job_id, job_id)
            self.assertTrue(Path(response.path).name.startswith("remote-"))

    def test_completed_float_video_is_promoted_to_course_cache(self):
        job_id = "5d03c70eae4e420aa9acf2317ad80827"

        class LocalClient:
            def __init__(self, video_path):
                self.video_path = video_path

            def get_job(self, requested_job_id):
                return FloatJobResult(
                    job_id=requested_job_id,
                    status="completed",
                    video_path=str(self.video_path),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "outputs" / "video" / "result.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"first-float-render")
            cache = CourseMediaCache(root / "outputs" / "course-media")
            cache_id = "a" * 64
            state = SimpleNamespace(
                float_client=LocalClient(video_path),
                course_media_cache=cache,
                course_media_jobs={job_id: cache_id},
                settings=SimpleNamespace(
                    project_root=root,
                    float_transfer_mode="path",
                ),
            )
            request = SimpleNamespace(app=SimpleNamespace(state=state))

            asyncio.run(get_video_media(job_id, request))

            self.assertEqual(cache.get(cache_id).read_bytes(), b"first-float-render")

    def test_concurrent_remote_media_requests_share_one_download(self):
        job_id = "f3899350d8ae42f999f972f71ce45ad5"

        class DownloadClient:
            downloads = 0

            def get_job(self, requested_job_id):
                return FloatJobResult(
                    job_id=requested_job_id,
                    status="completed",
                    video_path="/workspace/outputs/video.mp4",
                )

            def download_video(self, _requested_job_id, output_path):
                self.downloads += 1
                time.sleep(0.05)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"one-download")
                return output_path

        async def request_twice(request):
            return await asyncio.gather(
                get_video_media(job_id, request),
                get_video_media(job_id, request),
            )

        with tempfile.TemporaryDirectory() as directory:
            client = DownloadClient()
            state = SimpleNamespace(
                float_client=client,
                video_download_locks={},
                settings=SimpleNamespace(
                    project_root=Path(directory),
                    float_transfer_mode="upload",
                ),
            )
            request = SimpleNamespace(app=SimpleNamespace(state=state))

            responses = asyncio.run(request_twice(request))

            self.assertEqual(client.downloads, 1)
            self.assertEqual(len(responses), 2)
            self.assertEqual(Path(responses[0].path).read_bytes(), b"one-download")


if __name__ == "__main__":
    unittest.main()
