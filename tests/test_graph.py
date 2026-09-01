from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.adapters.llm import RuleBasedTeachingLLM
from app.graph import TeachingGraphRuntime, _matches_fixed_answer
from app.lessons import LESSONS, lesson_from_blueprint, register_lesson
from app.profile_store import SQLiteProfileStore


class TeachingGraphTests(unittest.TestCase):
    def test_fixed_choice_answers_accept_explicit_ordinals_and_letters(self):
        choices = ("2name", "user_name", "class")
        accepted = ("user_name",)
        for answer in ("第二个", "第二项", "第2个", "B", "选B", "中间那个"):
            with self.subTest(answer=answer):
                self.assertTrue(_matches_fixed_answer(answer, accepted, choices))
        self.assertFalse(_matches_fixed_answer("2", ("5",), ("4", "5", "6")))

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.runtime = TeachingGraphRuntime(
            checkpoint_path=root / "checkpoints.sqlite3",
            profiles=SQLiteProfileStore(root / "profiles.sqlite3"),
            llm=RuleBasedTeachingLLM(),
        )

    def tearDown(self):
        self.runtime.close()
        self.temp_dir.cleanup()

    def test_short_term_messages_accumulate_in_same_thread(self):
        self.runtime.invoke(
            user_id="u1",
            thread_id="thread-1",
            lesson_id="colors",
            text="我叫小明",
        )
        self.runtime.invoke(
            user_id="u1",
            thread_id="thread-1",
            lesson_id="colors",
            text="继续学习",
        )
        snapshot = self.runtime.graph.get_state(
            {"configurable": {"thread_id": "thread-1"}}
        )
        self.assertEqual(len(snapshot.values["messages"]), 4)

    def test_long_term_profile_is_shared_across_threads(self):
        first = self.runtime.invoke(
            user_id="u1",
            thread_id="thread-1",
            lesson_id="colors",
            text="我叫小明，请说慢一点",
        )
        second = self.runtime.invoke(
            user_id="u1",
            thread_id="thread-2",
            lesson_id="animals",
            text="继续学习",
        )
        self.assertEqual(first["profile"]["name"], "小明")
        self.assertEqual(second["profile"]["speech_rate"], 0.8)
        self.assertIn("小明", second["response_text"])

    def test_thread_cannot_be_reused_by_another_user(self):
        self.runtime.invoke(
            user_id="u1",
            thread_id="shared-thread",
            lesson_id="colors",
            text="你好",
        )
        with self.assertRaises(ValueError):
            self.runtime.invoke(
                user_id="u2",
                thread_id="shared-thread",
                lesson_id="colors",
                text="你好",
            )

    def test_python_lesson_branches_on_wrong_and_correct_answers(self):
        started = self.runtime.invoke(
            user_id="student-1",
            thread_id="python-lesson",
            lesson_id="python-basics",
            text="我想学Python变量",
        )
        self.assertEqual(started["lesson_phase"], "await_answer")
        self.assertEqual(started["concept_index"], 0)
        self.assertIn("x = x + 2", started["current_question"])

        wrong = self.runtime.invoke(
            user_id="student-1",
            thread_id="python-lesson",
            lesson_id="python-basics",
            text="6",
        )
        self.assertEqual(wrong["lesson_phase"], "await_answer")
        self.assertEqual(wrong["concept_index"], 0)
        self.assertEqual(wrong["attempt_count"], 1)

        correct = self.runtime.invoke(
            user_id="student-1",
            thread_id="python-lesson",
            lesson_id="python-basics",
            text="答案是5",
        )
        self.assertEqual(correct["concept_index"], 1)
        self.assertEqual(correct["score"], 1)
        self.assertEqual(correct["attempt_count"], 0)
        self.assertIn("user_name", correct["current_question"])
        self.assertEqual(correct["response_text"].count("回答正确"), 1)

    def test_completed_lesson_is_saved_in_long_term_profile(self):
        turns = [
            ("start", "我想学Python变量"),
            ("answer-1", "5"),
            ("answer-2", "user_name"),
            ("answer-3", "str"),
        ]
        result = None
        for _, text in turns:
            result = self.runtime.invoke(
                user_id="student-2",
                thread_id="python-complete",
                lesson_id="python-basics",
                text=text,
            )
        assert result is not None
        self.assertEqual(result["lesson_phase"], "complete")
        self.assertEqual(result["score"], 3)
        progress = result["profile"]["learning_progress"]["python-basics"]
        self.assertEqual(progress["status"], "complete")
        self.assertEqual(progress["score"], 3)

        reopened_thread = self.runtime.invoke(
            user_id="student-2",
            thread_id="another-thread",
            lesson_id="general-chat",
            text="继续学习",
        )
        self.assertEqual(
            reopened_thread["profile"]["learning_progress"]["python-basics"][
                "status"
            ],
            "complete",
        )

    def test_guided_lecture_auto_advances_and_pauses_only_at_checkpoints(self):
        started = self.runtime.invoke(
            user_id="lecture-student",
            thread_id="guided-lecture",
            lesson_id="python-lecture",
            text="",
            lesson_action="start",
        )
        self.assertEqual(started["lesson_phase"], "lecture")
        self.assertEqual(started["concept_index"], 0)
        self.assertEqual(started["current_question"], "")
        self.assertNotIn("问题：", started["response_text"])
        self.assertEqual(started["media_cache_scope"], "python-lecture/section-1")
        self.assertIn("变量可以理解为一个带名字的盒子", started["response_text"])

        checkpoint = self.runtime.invoke(
            user_id="lecture-student",
            thread_id="guided-lecture",
            lesson_id="python-lecture",
            text="",
            lesson_action="advance",
        )
        self.assertEqual(checkpoint["lesson_phase"], "await_checkpoint")
        self.assertEqual(checkpoint["concept_index"], 1)
        self.assertIn("user_name", checkpoint["current_question"])
        self.assertEqual(
            checkpoint["media_cache_scope"], "python-lecture/section-2"
        )

        detour = self.runtime.invoke(
            user_id="lecture-student",
            thread_id="guided-lecture",
            lesson_id="python-lecture",
            text="关键字是什么意思？",
            lesson_action="question",
        )
        self.assertEqual(detour["lesson_phase"], "await_checkpoint")
        self.assertEqual(detour["concept_index"], 1)
        self.assertEqual(detour["media_cache_scope"], "")

        next_checkpoint = self.runtime.invoke(
            user_id="lecture-student",
            thread_id="guided-lecture",
            lesson_id="python-lecture",
            text="user_name",
            lesson_action="answer",
        )
        self.assertEqual(next_checkpoint["lesson_phase"], "await_checkpoint")
        self.assertEqual(next_checkpoint["concept_index"], 2)
        self.assertEqual(next_checkpoint["score"], 1)
        self.assertIn("检查题", next_checkpoint["response_text"])
        self.assertEqual(
            next_checkpoint["media_cache_scope"],
            "python-lecture/section-3-after-correct",
        )

        completed = self.runtime.invoke(
            user_id="lecture-student",
            thread_id="guided-lecture",
            lesson_id="python-lecture",
            text="str",
            lesson_action="answer",
        )
        self.assertEqual(completed["lesson_phase"], "complete")
        self.assertEqual(completed["score"], 2)
        self.assertEqual(
            completed["media_cache_scope"], "python-lecture/complete"
        )
        progress = completed["profile"]["learning_progress"]["python-lecture"]
        self.assertEqual(progress["total"], 2)
        self.assertEqual(progress["status"], "complete")

    def test_guided_main_path_does_not_call_llm_generation(self):
        class NoGuidedGenerationLLM(RuleBasedTeachingLLM):
            def present_lecture_section(self, **_kwargs):
                raise AssertionError("fixed lecture must not call the LLM")

            def evaluate_answer(self, **_kwargs):
                raise AssertionError("choice checkpoint must not call the LLM")

            def complete_lesson(self, **_kwargs):
                raise AssertionError("fixed completion must not call the LLM")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = TeachingGraphRuntime(
                checkpoint_path=root / "checkpoints.sqlite3",
                profiles=SQLiteProfileStore(root / "profiles.sqlite3"),
                llm=NoGuidedGenerationLLM(),
            )
            try:
                runtime.invoke(
                    user_id="offline-guided",
                    thread_id="fixed-course",
                    lesson_id="python-lecture",
                    text="",
                    lesson_action="start",
                )
                runtime.invoke(
                    user_id="offline-guided",
                    thread_id="fixed-course",
                    lesson_id="python-lecture",
                    text="",
                    lesson_action="advance",
                )
                runtime.invoke(
                    user_id="offline-guided",
                    thread_id="fixed-course",
                    lesson_id="python-lecture",
                    text="user_name",
                    lesson_action="answer",
                )
                completed = runtime.invoke(
                    user_id="offline-guided",
                    thread_id="fixed-course",
                    lesson_id="python-lecture",
                    text="str",
                    lesson_action="answer",
                )
            finally:
                runtime.close()

        self.assertEqual(completed["lesson_phase"], "complete")

    def test_published_blueprint_runs_as_fixed_guided_course(self):
        lesson_id = "test-published-guided-course"
        blueprint = {
            "course_title": "人工审核课程",
            "lessons": [
                {
                    "title": "第一课",
                    "objective": "理解第一课",
                    "teaching_blocks": [
                        {"script": "这是不会调用语言模型的固定讲稿。"}
                    ],
                    "checkpoint": {
                        "question": "正确答案是什么？",
                        "choices": ["答案A", "答案B", "答案C"],
                        "correct_answer": "答案B",
                        "explanation": "教材中的正确答案是答案B。",
                    },
                }
            ],
        }
        register_lesson(lesson_from_blueprint(lesson_id, blueprint))
        try:
            started = self.runtime.invoke(
                user_id="published-user",
                thread_id="published-thread",
                lesson_id=lesson_id,
                text="",
                lesson_action="start",
            )
            completed = self.runtime.invoke(
                user_id="published-user",
                thread_id="published-thread",
                lesson_id=lesson_id,
                text="答案B",
                lesson_action="answer",
            )
        finally:
            LESSONS.pop(lesson_id, None)
        self.assertEqual(started["lesson_phase"], "await_checkpoint")
        self.assertIn("固定讲稿", started["response_text"])
        self.assertEqual(completed["lesson_phase"], "complete")
        self.assertIn("全部1个检查点", completed["response_text"])

    def test_two_lesson_published_course_keeps_both_checkpoints(self):
        blueprint = {
            "course_title": "两课时课程",
            "lessons": [
                {
                    "title": f"第{index + 1}课",
                    "objective": "理解知识点",
                    "teaching_blocks": [{"script": f"第{index + 1}课固定讲稿。"}],
                    "checkpoint": {
                        "question": f"第{index + 1}题？",
                        "choices": ["A", "B", "C"],
                        "correct_answer": "B",
                        "explanation": "答案是B。",
                    },
                }
                for index in range(2)
            ],
        }
        lesson = lesson_from_blueprint("two-section-course", blueprint)
        self.assertEqual(lesson.checkpoint_indices, (0, 1))
        self.assertEqual(lesson.assessment_total, 2)

    def test_interactive_main_path_is_fixed_and_does_not_call_llm(self):
        class NoPracticeGenerationLLM(RuleBasedTeachingLLM):
            def present_concept(self, **_kwargs):
                raise AssertionError("fixed practice must not call the LLM")

            def evaluate_answer(self, **_kwargs):
                raise AssertionError("fixed answer evaluation must not call the LLM")

            def complete_lesson(self, **_kwargs):
                raise AssertionError("fixed completion must not call the LLM")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = TeachingGraphRuntime(
                checkpoint_path=root / "checkpoints.sqlite3",
                profiles=SQLiteProfileStore(root / "profiles.sqlite3"),
                llm=NoPracticeGenerationLLM(),
            )
            try:
                started = runtime.invoke(
                    user_id="fixed-practice",
                    thread_id="fixed-practice-thread",
                    lesson_id="python-basics",
                    text="开始Python变量课程",
                    lesson_action="start",
                )
                second = runtime.invoke(
                    user_id="fixed-practice",
                    thread_id="fixed-practice-thread",
                    lesson_id="python-basics",
                    text="答案是5",
                    lesson_action="answer",
                )
                third = runtime.invoke(
                    user_id="fixed-practice",
                    thread_id="fixed-practice-thread",
                    lesson_id="python-basics",
                    text="user_name",
                    lesson_action="answer",
                )
                completed = runtime.invoke(
                    user_id="fixed-practice",
                    thread_id="fixed-practice-thread",
                    lesson_id="python-basics",
                    text="str",
                    lesson_action="answer",
                )
            finally:
                runtime.close()

        self.assertEqual(started["media_cache_scope"], "python-basics/section-1")
        self.assertEqual(
            second["media_cache_scope"],
            "python-basics/section-2-after-correct",
        )
        self.assertEqual(
            third["media_cache_scope"],
            "python-basics/section-3-after-correct",
        )
        self.assertEqual(completed["lesson_phase"], "complete")
        self.assertEqual(completed["media_cache_scope"], "python-basics/complete")

    def test_interactive_question_detour_preserves_the_current_exercise(self):
        started = self.runtime.invoke(
            user_id="question-student",
            thread_id="practice-question",
            lesson_id="python-basics",
            text="开始",
            lesson_action="start",
        )
        detour = self.runtime.invoke(
            user_id="question-student",
            thread_id="practice-question",
            lesson_id="python-basics",
            text="为什么等号不是数学里的相等？",
            lesson_action="question",
        )
        answered = self.runtime.invoke(
            user_id="question-student",
            thread_id="practice-question",
            lesson_id="python-basics",
            text="5",
            lesson_action="answer",
        )

        self.assertEqual(started["lesson_phase"], "await_answer")
        self.assertEqual(detour["lesson_phase"], "await_answer")
        self.assertEqual(detour["concept_index"], 0)
        self.assertEqual(detour["attempt_count"], 0)
        self.assertEqual(detour["score"], 0)
        self.assertEqual(detour["media_cache_scope"], "")
        self.assertIn("为什么等号不是数学里的相等", detour["response_text"])
        self.assertEqual(answered["concept_index"], 1)
        self.assertEqual(answered["score"], 1)

    def test_interactive_wrong_feedback_has_two_fixed_cacheable_tiers(self):
        self.runtime.invoke(
            user_id="wrong-student",
            thread_id="practice-wrong",
            lesson_id="python-basics",
            text="开始",
            lesson_action="start",
        )
        first_wrong = self.runtime.invoke(
            user_id="wrong-student",
            thread_id="practice-wrong",
            lesson_id="python-basics",
            text="15",
            lesson_action="answer",
        )
        second_wrong = self.runtime.invoke(
            user_id="wrong-student",
            thread_id="practice-wrong",
            lesson_id="python-basics",
            text="6",
            lesson_action="answer",
        )
        repeated_wrong = self.runtime.invoke(
            user_id="wrong-student",
            thread_id="practice-wrong",
            lesson_id="python-basics",
            text="4",
            lesson_action="answer",
        )

        self.assertFalse(first_wrong["evaluation_correct"])
        self.assertEqual(
            first_wrong["media_cache_scope"],
            "python-basics/concept-1-wrong-tier-1",
        )
        self.assertEqual(
            second_wrong["media_cache_scope"],
            "python-basics/concept-1-wrong-tier-2",
        )
        self.assertEqual(
            repeated_wrong["media_cache_scope"],
            "python-basics/concept-1-wrong-tier-2",
        )
        self.assertNotEqual(first_wrong["response_text"], second_wrong["response_text"])
        self.assertEqual(second_wrong["response_text"], repeated_wrong["response_text"])

    def test_dynamic_lecture_advances_for_five_generated_sections_without_cache(self):
        result = self.runtime.invoke(
            user_id="dynamic-student",
            thread_id="dynamic-thread",
            lesson_id="default",
            text="高等数学中的函数",
            lesson_action="dynamic_start",
        )
        self.assertEqual(result["lesson_phase"], "dynamic_lecture")
        self.assertEqual(result["dynamic_section_index"], 0)
        self.assertEqual(result["media_cache_scope"], "")

        for _ in range(4):
            result = self.runtime.invoke(
                user_id="dynamic-student",
                thread_id="dynamic-thread",
                lesson_id="default",
                text="自动继续",
                lesson_action="dynamic_advance",
            )

        self.assertEqual(result["lesson_phase"], "dynamic_complete")
        self.assertEqual(result["dynamic_section_index"], 4)
        self.assertEqual(result["dynamic_section_total"], 5)
        self.assertEqual(result["media_cache_scope"], "")

    def test_dynamic_advance_without_started_thread_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "动态讲授会话状态已失效"):
            self.runtime.invoke(
                user_id="dynamic-student",
                thread_id="missing-dynamic-thread",
                lesson_id="default",
                text="自动继续",
                lesson_action="dynamic_advance",
            )

    def test_dynamic_start_requires_an_explicit_topic(self):
        with self.assertRaisesRegex(ValueError, "明确的讲授主题"):
            self.runtime.invoke(
                user_id="dynamic-student",
                thread_id="topic-required-thread",
                lesson_id="default",
                text="请根据当前对话确定主题并开始连续讲授",
                lesson_action="dynamic_start",
            )

    def test_corrupted_saved_score_is_clamped_on_next_request(self):
        self.runtime.profiles.merge(
            "overflow-student",
            {
                "learning_progress": {
                    "python-lecture": {
                        "lesson_title": "Python变量基础课程",
                        "status": "complete",
                        "score": 3,
                        "total": 2,
                    }
                }
            },
        )

        result = self.runtime.invoke(
            user_id="overflow-student",
            thread_id="overflow-thread",
            lesson_id="default",
            text="你好",
        )

        progress = result["profile"]["learning_progress"]["python-lecture"]
        self.assertEqual(progress["score"], 2)
        self.assertEqual(progress["total"], 2)


if __name__ == "__main__":
    unittest.main()
