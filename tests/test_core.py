from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.adapters.float_renderer import FloatWorkerClient
from app.adapters.llm import (
    LLMResponseFormatError,
    QwenTeachingLLM,
    RuleBasedTeachingLLM,
)
from app.adapters.tts import QwenTTS, build_teacher_instruction
from app.config import Settings
from app.profile_store import SQLiteProfileStore
from app.prompts import (
    build_concept_system_prompt,
    build_evaluation_system_prompt,
    build_lecture_section_system_prompt,
    build_dynamic_lecture_system_prompt,
)


class ProfileStoreTests(unittest.TestCase):
    def test_profile_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.sqlite3"
            store = SQLiteProfileStore(path)
            store.merge("u1", {"name": "小明", "speech_rate": 0.8})
            store.close()

            reopened = SQLiteProfileStore(path)
            self.assertEqual(reopened.get("u1")["name"], "小明")
            self.assertEqual(reopened.get("u1")["speech_rate"], 0.8)
            reopened.close()


class SettingsTests(unittest.TestCase):
    def test_reads_model_studio_export_without_copying_key_to_env(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials_path = Path(directory) / "credentials.csv"
            credentials_path.write_text(
                "id,123\n"
                "apiKey,sk-test-secret\n"
                "openAiCompatible,https://example.test/compatible-mode/v1\n"
                "dashScope,https://example.test/api/v1\n",
                encoding="utf-8",
            )
            env = {
                "VT_LLM_MODE": "qwen",
                "VT_QWEN_CREDENTIALS_FILE": str(credentials_path),
                "VT_QWEN_MODEL": "qwen3.7-flash",
                "VT_DATA_DIR": str(Path(directory) / "data"),
            }
            with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv"):
                settings = Settings.from_env()

            self.assertEqual(settings.qwen_api_key, "sk-test-secret")
            self.assertEqual(
                settings.qwen_base_url,
                "https://example.test/compatible-mode/v1",
            )
            self.assertEqual(settings.qwen_model, "qwen3.7-flash")
            self.assertEqual(settings.qwen_tts_base_url, "https://example.test/api/v1")
            self.assertEqual(settings.float_worker_url, "http://127.0.0.1:8011")
            self.assertEqual(settings.float_transfer_mode, "path")
            self.assertEqual(
                settings.avatar_reference_image.name,
                "real-teacher-002-float-aligned.png",
            )


class QwenTTSTests(unittest.TestCase):
    def test_teacher_instruction_uses_emotion_and_rate(self):
        instruction = build_teacher_instruction("happy", 0.75)
        self.assertIn("开心", instruction)
        self.assertIn("语速较慢", instruction)

    def test_synthesizes_inline_audio_without_exposing_key(self):
        class FakeResponse:
            def __init__(self, payload=None, content=b""):
                self._payload = payload
                self.content = content

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeSession:
            last_post = None

            def post(self, url, **kwargs):
                self.last_post = (url, kwargs)
                return FakeResponse(
                    {
                        "status_code": 200,
                        "request_id": "request-1",
                        "output": {
                            "audio": {
                                "data": base64.b64encode(b"RIFFtest").decode(),
                                "url": "",
                            }
                        },
                        "usage": {"characters": 4},
                    }
                )

        import base64

        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            tts = QwenTTS(
                base_url="https://example.test/api/v1",
                api_key="sk-secret",
                model="qwen3-tts-instruct-flash",
                voice="Cherry",
                output_dir=Path(directory),
                session=session,
            )
            result = tts.synthesize("回答正确", emotion="happy", speech_rate=0.8)

            self.assertEqual(result.audio_path.read_bytes(), b"RIFFtest")
            self.assertEqual(result.characters, 4)
            self.assertNotIn("sk-secret", str(session.last_post[1]["json"]))
            self.assertEqual(
                session.last_post[1]["headers"]["Authorization"], "Bearer sk-secret"
            )


class FloatWorkerClientTests(unittest.TestCase):
    def test_health_retries_a_transient_connection_reset(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "ready"}

        class FlakySession:
            calls = 0
            last_kwargs = None

            def get(self, _url, **kwargs):
                self.calls += 1
                self.last_kwargs = kwargs
                if self.calls == 1:
                    raise ConnectionResetError("stale tunneled connection")
                return FakeResponse()

        session = FlakySession()
        client = FloatWorkerClient(
            "http://127.0.0.1:18011",
            session=session,
        )

        self.assertEqual(client.health()["status"], "ready")
        self.assertEqual(session.calls, 2)
        self.assertEqual(session.last_kwargs["headers"]["Connection"], "close")

    def test_submits_generated_audio_and_parses_job(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "job_id": "job-1",
                    "status": "queued",
                    "video_path": "",
                    "elapsed_seconds": 0,
                    "error": "",
                }

        class FakeSession:
            last_url = ""
            last_json = None

            def post(self, url, **kwargs):
                self.last_url = url
                self.last_json = kwargs["json"]
                return FakeResponse()

        session = FakeSession()
        client = FloatWorkerClient(
            "http://127.0.0.1:8011/", session=session
        )
        job = client.submit(
            audio_path=Path("audio.wav"),
            reference_image=Path("teacher.png"),
            emotion="happy",
        )

        self.assertEqual(job.job_id, "job-1")
        self.assertEqual(job.status, "queued")
        self.assertEqual(session.last_url, "http://127.0.0.1:8011/v1/jobs")
        self.assertEqual(session.last_json["emotion"], "happy")
        self.assertFalse(session.last_json["no_crop"])

    def test_upload_mode_sends_wav_body_without_local_paths(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"job_id": "job-2", "status": "queued"}

        class FakeSession:
            last_url = ""
            last_kwargs = None
            uploaded = b""

            def post(self, url, **kwargs):
                self.last_url = url
                self.last_kwargs = kwargs
                self.uploaded = kwargs["data"].read()
                return FakeResponse()

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "reply.wav"
            audio.write_bytes(b"RIFFtestWAVEaudio")
            session = FakeSession()
            client = FloatWorkerClient(
                "http://127.0.0.1:18011",
                transfer_mode="upload",
                session=session,
            )

            job = client.submit(
                audio_path=audio,
                reference_image=Path("G:/local-only-teacher.png"),
                emotion="happy",
            )

            self.assertEqual(job.job_id, "job-2")
            self.assertEqual(
                session.last_url,
                "http://127.0.0.1:18011/v1/jobs/upload",
            )
            self.assertEqual(session.uploaded, audio.read_bytes())
            self.assertEqual(session.last_kwargs["params"]["emotion"], "happy")
            self.assertNotIn("reference_image", session.last_kwargs["params"])

    def test_download_video_uses_worker_media_endpoint(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"video-", b"bytes"))

        class FakeSession:
            last_url = ""

            def get(self, url, **kwargs):
                self.last_url = url
                self.last_kwargs = kwargs
                return FakeResponse()

        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            client = FloatWorkerClient(
                "http://127.0.0.1:18011",
                transfer_mode="upload",
                session=session,
            )
            output = Path(directory) / "remote.mp4"

            result = client.download_video("job-3", output)

            self.assertEqual(result.read_bytes(), b"video-bytes")
            self.assertEqual(
                session.last_url,
                "http://127.0.0.1:18011/v1/jobs/job-3/media",
            )
            self.assertTrue(session.last_kwargs["stream"])


class RuleBasedLLMTests(unittest.TestCase):
    def test_extracts_explicit_stable_preferences(self):
        llm = RuleBasedTeachingLLM()
        plan = llm.generate("我叫小明，请说慢一点", {}, [])
        self.assertEqual(plan.memory_update["name"], "小明")
        self.assertEqual(plan.memory_update["speech_rate"], 0.8)
        self.assertEqual(plan.speech_rate, 0.8)

    def test_reuses_profile(self):
        llm = RuleBasedTeachingLLM()
        plan = llm.generate(
            "继续学习", {"name": "小明", "speech_rate": 0.8}, []
        )
        self.assertIn("小明", plan.reply_text)
        self.assertEqual(plan.speech_rate, 0.8)


class QwenLLMTests(unittest.TestCase):
    @staticmethod
    def _fake_llm(content: str):
        class FakeCompletions:
            last_kwargs = None

            def create(self, **kwargs):
                self.last_kwargs = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
                )

        llm = QwenTeachingLLM.__new__(QwenTeachingLLM)
        llm.model = "test-model"
        llm.trace = SimpleNamespace(write=lambda record: None)
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        return llm

    def test_unwraps_single_object_array_without_retry(self):
        llm = self._fake_llm(
            '[{"reply_text":"数组也能恢复。","emotion":"neutral",'
            '"speech_rate":1.0,"memory_update":{}}]'
        )

        plan = llm.generate("继续", {}, [{"role": "user", "content": "继续"}])

        self.assertEqual(plan.reply_text, "数组也能恢复。")

    def test_free_chat_prompt_excludes_course_progress(self):
        llm = self._fake_llm(
            '{"reply_text":"我们从基础开始。","emotion":"neutral",'
            '"speech_rate":1.0,"memory_update":{}}'
        )

        llm.generate(
            "我想学习Python",
            {
                "name": "小明",
                "favorite_topics": ["Python"],
                "learning_progress": {
                    "python-basics": {
                        "status": "await_answer",
                        "current_concept": "变量命名",
                    }
                },
            },
            [{"role": "user", "content": "我想学习Python"}],
        )

        messages = llm.client.chat.completions.last_kwargs["messages"]
        system_prompt = messages[0]["content"]
        self.assertIn("小明", system_prompt)
        self.assertIn("Python", system_prompt)
        self.assertNotIn("learning_progress", system_prompt)
        self.assertNotIn("变量命名", system_prompt)
        self.assertIn("不要声称用户已经完成", system_prompt)
        self.assertIn("最新问题为最高优先级", system_prompt)

    def test_retrieval_context_is_added_to_chat_system_prompt(self):
        llm = self._fake_llm(
            '{"reply_text":"教材认为泛化能力很重要。","emotion":"neutral",'
            '"speech_rate":1.0,"memory_update":{}}'
        )

        llm.generate(
            "什么是泛化能力？",
            {},
            [{"role": "user", "content": "什么是泛化能力？"}],
            source_context="[PDF第28页｜模型评估]\n泛化能力是模型对未见样本的适应能力。",
        )

        system_prompt = llm.client.chat.completions.last_kwargs["messages"][0]["content"]
        self.assertIn("PDF第28页", system_prompt)
        self.assertIn("泛化能力是模型对未见样本", system_prompt)
        self.assertIn("不得编造", system_prompt)

    def test_rejects_non_object_json_shape(self):
        llm = self._fake_llm('[1, 2]')

        with self.assertRaises(LLMResponseFormatError):
            llm.generate("继续", {}, [{"role": "user", "content": "继续"}])

    def test_dynamic_lecture_ends_request_with_current_user_instruction(self):
        llm = self._fake_llm(
            '{"reply_text":"讲授内容。","emotion":"neutral",'
            '"speech_rate":1.0,"memory_update":{}}'
        )

        llm.generate_dynamic_lecture(
            topic="Python装饰器",
            section_number=3,
            section_total=5,
            profile={},
            recent_messages=[{"role": "assistant", "content": "上一节内容"}],
        )

        messages = llm.client.chat.completions.last_kwargs["messages"]
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("第3/5节", messages[-1]["content"])
        self.assertIn("不要复述上一节", messages[-1]["content"])

    def test_parses_structured_reply_and_filters_memory_keys(self):
        content = (
            '{"reply_text":"很好，我们继续。","emotion":"happy",'
            '"speech_rate":0.85,"memory_update":'
            '{"teaching_style":"鼓励式","diagnosis":"不应保存"}}'
        )

        class FakeCompletions:
            last_kwargs = None

            def create(self, **kwargs):
                self.last_kwargs = kwargs
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=content)
                        )
                    ]
                )

        llm = QwenTeachingLLM.__new__(QwenTeachingLLM)
        llm.model = "test-model"
        llm.trace = SimpleNamespace(write=lambda record: None)
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        plan = llm.generate("继续", {}, [{"role": "user", "content": "继续"}])

        self.assertEqual(plan.reply_text, "很好，我们继续。")
        self.assertEqual(plan.speech_rate, 0.85)
        self.assertEqual(plan.memory_update, {"teaching_style": "鼓励式"})
        self.assertEqual(
            llm.client.chat.completions.last_kwargs["extra_body"],
            {"enable_thinking": False},
        )


class PromptTemplateTests(unittest.TestCase):
    def test_dynamic_lecture_prompt_is_teacher_led(self):
        prompt = build_dynamic_lecture_system_prompt(
            profile={}, topic="函数与极限", section_number=2, section_total=5
        )
        self.assertIn("3到6个", prompt)
        self.assertIn("不要向学生提问", prompt)
        self.assertIn("第2/5部分", prompt)

    def test_guided_lecture_prompt_does_not_ask_for_continue(self):
        prompt = build_lecture_section_system_prompt(
            profile={},
            lesson_title="Python变量基础课程",
            concept_title="变量赋值",
            objective="理解赋值",
            explanation="等号把右侧的值赋给左侧变量。",
            reference_answer="x最后等于5。",
            section_number=1,
            section_total=3,
        )
        self.assertIn("不要提问", prompt)
        self.assertIn("不要要求用户输入“继续”", prompt)
        self.assertIn("3到5个", prompt)

    def test_concept_prompt_forbids_duplicate_evaluation(self):
        prompt = build_concept_system_prompt(
            profile={},
            lesson_title="Python变量基础",
            concept_title="变量命名",
            objective="识别合法变量名",
            explanation="变量名不能以数字开头。",
            question="哪个变量名合法？",
        )
        self.assertIn("不要评价用户上一条回答", prompt)
        self.assertIn("禁止使用“太棒了”", prompt)
        self.assertIn("2到3个短句", prompt)

    def test_correct_evaluation_is_one_short_reason(self):
        prompt = build_evaluation_system_prompt(
            profile={},
            concept_title="变量命名",
            question="哪个变量名合法？",
            reference_answer="user_name合法。",
            attempt_count=0,
        )
        self.assertIn("只用一句话", prompt)
        self.assertIn("只允许一次肯定", prompt)
        self.assertIn("不超过50个汉字", prompt)

if __name__ == "__main__":
    unittest.main()
