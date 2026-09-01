from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.api import app
from app.course_design import (
    CourseDesignError,
    QwenCourseDesigner,
    build_course_design_prompt,
    build_course_source,
    chapter_generation_plan,
    design_chapter_in_batches,
    normalize_course_blueprint,
    recover_editable_course_blueprint,
    split_course_page_batches,
)


def _blueprint() -> dict:
    return {
        "course_title": "模型评估入门",
        "course_description": "理解模型评估的基本问题与方法。",
        "audience": "机器学习初学者",
        "total_minutes": 20,
        "learning_objectives": ["解释经验误差和过拟合"],
        "lessons": [
            {
                "title": "经验误差与过拟合",
                "objective": "区分训练误差与泛化误差",
                "estimated_minutes": 10,
                "source_pages": [23, 24],
                "teaching_blocks": [
                    {
                        "title": "核心概念",
                        "script": "经验误差是在训练集上的误差。",
                        "source_pages": [23],
                    }
                ],
                "checkpoint": {
                    "question": "哪一项描述的是经验误差？",
                    "choices": ["训练集上的误差", "测试集上的误差", "没有误差"],
                    "correct_answer": "训练集上的误差",
                    "explanation": "经验误差对应训练集上的误差。",
                    "source_pages": [23],
                },
            }
        ],
    }


class CourseDesignTests(unittest.TestCase):
    def test_builds_page_delimited_source(self):
        source, pages = build_course_source(
            [
                {"page_number": 23, "has_text_layer": True, "text": "正文A"},
                {"page_number": 24, "has_text_layer": True, "text": "正文B"},
            ]
        )
        self.assertEqual(pages, {23, 24})
        self.assertIn("教材PDF第23页", source)
        self.assertIn("教材PDF第24页", source)

    def test_prompt_requires_grounded_editable_draft(self):
        prompt = build_course_design_prompt(
            filename="教材.pdf",
            source_text="===== 教材PDF第23页 =====\n正文",
            audience="机器学习初学者",
            lesson_count=1,
            target_minutes=20,
        )
        self.assertIn("严格生成1个课时", prompt)
        self.assertIn("不得使用原文之外的事实", prompt)
        self.assertIn("source_pages", prompt)
        self.assertIn("虚拟教师可直接朗读", prompt)
        self.assertIn("不得压缩掉教材结构", prompt)

    def test_normalizes_and_validates_page_references(self):
        result = normalize_course_blueprint(
            _blueprint(),
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertEqual(result["status"], "draft")
        self.assertTrue(result["grounding"]["page_references_validated"])
        self.assertTrue(result["grounding"]["human_review_required"])
        self.assertEqual(result["lessons"][0]["checkpoint"]["source_pages"], [23])
        self.assertEqual(result["grounding"]["coverage_ratio"], 1.0)

    def test_flags_low_page_coverage_for_human_review(self):
        blueprint = _blueprint()
        blueprint["lessons"][0]["source_pages"] = [23]
        result = normalize_course_blueprint(
            blueprint,
            allowed_pages={23, 24, 25, 26},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertEqual(result["grounding"]["covered_pages"], [23])
        self.assertEqual(result["grounding"]["uncovered_pages"], [24, 25, 26])
        self.assertTrue(any("覆盖不足65%" in note for note in result["review_notes"]))

    def test_rejects_hallucinated_page_reference(self):
        blueprint = _blueprint()
        blueprint["lessons"][0]["source_pages"] = [999]
        with self.assertRaisesRegex(CourseDesignError, "没有引用所选教材页"):
            normalize_course_blueprint(
                blueprint,
                allowed_pages={23, 24},
                expected_lesson_count=1,
                default_audience="机器学习初学者",
            )

    def test_rejects_answer_outside_choices(self):
        blueprint = _blueprint()
        blueprint["lessons"][0]["checkpoint"]["correct_answer"] = "不存在的选项"
        with self.assertRaisesRegex(CourseDesignError, "正确答案不在选项中"):
            normalize_course_blueprint(
                blueprint,
                allowed_pages={23, 24},
                expected_lesson_count=1,
                default_audience="机器学习初学者",
            )

    def test_resolves_letter_answer_to_prefixed_choice(self):
        blueprint = _blueprint()
        checkpoint = blueprint["lessons"][0]["checkpoint"]
        checkpoint["choices"] = ["A. 训练误差", "B. 泛化误差", "C. 没有误差"]
        checkpoint["correct_answer"] = "B"
        result = normalize_course_blueprint(
            blueprint,
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertEqual(
            result["lessons"][0]["checkpoint"]["correct_answer"],
            "B. 泛化误差",
        )

    def test_repairs_unreplaced_objective_placeholder_and_records_review_note(self):
        blueprint = _blueprint()
        blueprint["lessons"][0]["objective"] = "本课时学习目标"
        result = normalize_course_blueprint(
            blueprint,
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertIn("经验误差与过拟合", result["lessons"][0]["objective"])
        self.assertEqual(len(result["review_notes"]), 1)

    def test_recovery_auto_fixes_safe_block_title_placeholder(self):
        blueprint = _blueprint()
        blueprint["lessons"][0]["teaching_blocks"][0]["title"] = "讲授段落名称"
        result = recover_editable_course_blueprint(
            blueprint,
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertEqual(result["quality_status"], "auto_fixed")
        self.assertEqual(result["validation_issues"], [])
        self.assertNotEqual(
            result["lessons"][0]["teaching_blocks"][0]["title"],
            "讲授段落名称",
        )
        self.assertTrue(result["auto_fixes"])

    def test_recovery_keeps_duplicate_choices_for_manual_correction(self):
        blueprint = _blueprint()
        checkpoint = blueprint["lessons"][0]["checkpoint"]
        checkpoint["choices"] = ["训练误差", "训练误差", "没有误差"]
        checkpoint["correct_answer"] = "训练误差"
        result = recover_editable_course_blueprint(
            blueprint,
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        self.assertEqual(result["quality_status"], "needs_fix")
        self.assertEqual(result["lessons"][0]["checkpoint"]["choices"][1], "训练误差")
        self.assertTrue(
            any(issue["path"].endswith("checkpoint.choices") for issue in result["validation_issues"])
        )

    def test_recovery_safely_reduces_four_choices_and_removes_empty_checkpoint_block(self):
        blueprint = _blueprint()
        lesson = blueprint["lessons"][0]
        lesson["checkpoint"]["choices"] = ["A.甲", "B.乙", "C.丙", "D.丁"]
        lesson["checkpoint"]["correct_answer"] = "D"
        lesson["teaching_blocks"].append(
            {"title": "检查题", "script": "", "source_pages": [23]}
        )
        result = recover_editable_course_blueprint(
            blueprint,
            allowed_pages={23, 24},
            expected_lesson_count=1,
            default_audience="机器学习初学者",
        )
        checkpoint = result["lessons"][0]["checkpoint"]
        self.assertEqual(result["quality_status"], "auto_fixed")
        self.assertEqual(len(checkpoint["choices"]), 3)
        self.assertIn("D.丁", checkpoint["choices"])
        self.assertEqual(checkpoint["correct_answer"], "D.丁")
        self.assertEqual(len(result["lessons"][0]["teaching_blocks"]), 1)

    def test_qwen_designer_returns_recovered_draft_without_second_model_call(self):
        class FakeTrace:
            def __init__(self):
                self.records = []

            def write(self, record):
                self.records.append(record)

        class FakeLLM:
            def __init__(self):
                self.calls = 0
                self.trace = FakeTrace()

            def _complete_json(self, **_kwargs):
                self.calls += 1
                blueprint = _blueprint()
                checkpoint = blueprint["lessons"][0]["checkpoint"]
                checkpoint["choices"] = ["A.甲", "B.乙", "C.丙", "D.丁"]
                checkpoint["correct_answer"] = "D"
                return blueprint

        designer = object.__new__(QwenCourseDesigner)
        designer.llm = FakeLLM()
        designer.model = "fake-qwen"
        result = designer.design(
            filename="教材.pdf",
            pages=[{"page_number": 23, "has_text_layer": True, "text": "教材正文"}],
            audience="机器学习初学者",
            lesson_count=1,
            target_minutes=20,
        )
        self.assertEqual(designer.llm.calls, 1)
        self.assertEqual(result["quality_status"], "auto_fixed")
        self.assertEqual(len(result["lessons"][0]["checkpoint"]["choices"]), 3)
        self.assertEqual(len(designer.llm.trace.records), 1)

    def test_course_design_api_returns_draft_without_media_generation(self):
        class FakeDesigner:
            def design(self, **_kwargs):
                result = normalize_course_blueprint(
                    _blueprint(),
                    allowed_pages={23, 24},
                    expected_lesson_count=1,
                    default_audience="机器学习初学者",
                )
                result["generator"] = {"provider": "fake", "model": "fake-course-model"}
                return result

        with TestClient(app) as client:
            client.app.state.course_designer = FakeDesigner()
            response = client.post(
                "/v1/course-imports/design",
                json={
                    "filename": "教材.pdf",
                    "audience": "机器学习初学者",
                    "lesson_count": 1,
                    "target_minutes": 20,
                    "pages": [
                        {
                            "page_number": 23,
                            "has_text_layer": True,
                            "text": "经验误差与过拟合的教材正文。",
                        },
                        {
                            "page_number": 24,
                            "has_text_layer": True,
                            "text": "模型评估方法的教材正文。",
                        },
                    ],
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["generator"]["model"], "fake-course-model")

    def test_splits_long_chapter_without_splitting_source_pages(self):
        pages = [
            {
                "page_number": index,
                "has_text_layer": True,
                "text": "正文" * 1_100,
            }
            for index in range(1, 26)
        ]
        batches = split_course_page_batches(pages)
        self.assertGreater(len(batches), 1)
        flattened = [page["page_number"] for batch in batches for page in batch]
        self.assertEqual(flattened, list(range(1, 26)))
        plan = chapter_generation_plan(pages, requested_lessons=4)
        self.assertEqual(plan["estimated_model_calls"], len(batches))
        self.assertEqual(sum(plan["lesson_counts"]), 4)

    def test_recommends_more_lessons_for_a_twenty_page_chapter(self):
        pages = [
            {"page_number": index, "has_text_layer": True, "text": "正文" * 100}
            for index in range(1, 21)
        ]
        plan = chapter_generation_plan(pages, requested_lessons=2)
        self.assertEqual(plan["effective_lesson_count"], 2)
        self.assertEqual(plan["recommended_lesson_count"], 4)

    def test_defaults_to_teachable_textbook_section_count(self):
        pages = [
            {
                "page_number": 1,
                "has_text_layer": True,
                "text": "正文",
                "headings": [
                    {"level": 2, "title": "3.1 基本形式", "page_number": 1},
                    {"level": 2, "title": "3.2 线性回归", "page_number": 1},
                ],
            },
            {
                "page_number": 2,
                "has_text_layer": True,
                "text": "正文",
                "headings": [
                    {"level": 2, "title": "3.3 阅读材料", "page_number": 2},
                ],
            },
        ]
        plan = chapter_generation_plan(pages, requested_lessons=1)
        self.assertEqual(plan["recommended_lesson_count"], 2)
        self.assertEqual(
            [item["title"] for item in plan["detected_sections"]],
            ["3.1 基本形式", "3.2 线性回归"],
        )

    def test_designs_batches_and_merges_one_chapter_draft(self):
        class FakeBatchDesigner:
            def __init__(self):
                self.calls = 0

            def design(self, **kwargs):
                self.calls += 1
                source_pages = [page["page_number"] for page in kwargs["pages"]]
                lesson_total = kwargs["lesson_count"]
                lessons = []
                for lesson_index in range(lesson_total):
                    lessons.append(
                        {
                            "title": f"批次{self.calls}课时{lesson_index + 1}",
                            "objective": "理解本批次知识点",
                            "estimated_minutes": 10,
                            "source_pages": source_pages,
                            "teaching_blocks": [],
                            "checkpoint": {},
                        }
                    )
                return {
                    "course_title": "分批草稿",
                    "course_description": "测试",
                    "audience": kwargs["audience"],
                    "total_minutes": 10 * lesson_total,
                    "learning_objectives": [f"目标{self.calls}"],
                    "lessons": lessons,
                    "status": "draft",
                    "grounding": {
                        "source_pages": source_pages,
                        "human_review_required": True,
                    },
                    "review_notes": [],
                    "generator": {"provider": "fake", "model": "fake-model"},
                }

        pages = [
            {
                "page_number": index,
                "has_text_layer": True,
                "text": "章节正文" * 800,
            }
            for index in range(1, 26)
        ]
        designer = FakeBatchDesigner()
        result = design_chapter_in_batches(
            designer,
            filename="教材.pdf",
            chapter_title="第1章 测试",
            pages=pages,
            audience="本科生",
            lesson_count=4,
            target_minutes=60,
        )
        self.assertEqual(result["course_title"], "第1章 测试课程")
        self.assertEqual(len(result["lessons"]), 4)
        self.assertEqual(result["generator"]["model_calls"], designer.calls)
        self.assertEqual(result["grounding"]["source_pages"], list(range(1, 26)))

    def test_batch_failure_reports_failed_position_and_possible_model_calls(self):
        class FailingSecondBatchDesigner:
            def __init__(self):
                self.calls = 0

            def design(self, **_kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise CourseDesignError("返回结构无法恢复")
                return {
                    "lessons": [],
                    "learning_objectives": [],
                    "review_notes": [],
                    "grounding": {"source_pages": [1]},
                    "generator": {"model": "fake-model"},
                }

        pages = [
            {"page_number": index, "has_text_layer": True, "text": "正文" * 100}
            for index in range(1, 22)
        ]
        designer = FailingSecondBatchDesigner()
        with self.assertRaisesRegex(
            CourseDesignError,
            "第2/2批生成失败.*此前1批已返回.*可能已发起2次模型调用",
        ):
            design_chapter_in_batches(
                designer,
                filename="教材.pdf",
                chapter_title="第1章 测试",
                pages=pages,
                audience="本科生",
                lesson_count=2,
                target_minutes=20,
            )


if __name__ == "__main__":
    unittest.main()
