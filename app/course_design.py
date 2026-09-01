from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.adapters.llm import (
    LLMProviderError,
    LLMResponseFormatError,
    QwenTeachingLLM,
)


MAX_COURSE_SOURCE_CHARS = 24_000
MAX_COURSE_PAGES = 20
MAX_CHAPTER_BATCHES = 8
_NON_TEACHING_SECTION_MARKERS = (
    "阅读材料",
    "本章小结",
    "小结",
    "习题",
    "练习题",
    "参考文献",
    "进一步阅读",
)


class CourseDesignError(ValueError):
    """The selected source or generated course blueprint is invalid."""


def teachable_sections_from_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deduplicated textbook subsections that should become lessons."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        for heading in page.get("headings", []):
            try:
                level = int(heading.get("level", 0))
                page_number = int(heading.get("page_number", page.get("page_number", 0)))
            except (TypeError, ValueError):
                continue
            title = " ".join(str(heading.get("title", "")).split())
            if level < 2 or not title or title in seen:
                continue
            if any(marker in title for marker in _NON_TEACHING_SECTION_MARKERS):
                continue
            candidates.append(
                {"level": level, "title": title, "page_number": page_number}
            )
            seen.add(title)
    if not candidates:
        return []
    shallowest = min(item["level"] for item in candidates)
    return [item for item in candidates if item["level"] == shallowest]


def _required_text(value: Any, field: str, *, max_length: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CourseDesignError(f"课程蓝图缺少有效字段：{field}")
    return value.strip()[:max_length]


def _specific_text(value: Any, field: str, *, max_length: int = 2_000) -> str:
    text = _required_text(value, field, max_length=max_length)
    placeholders = {
        "课程名称",
        "课程简介",
        "课时名称",
        "本课时学习目标",
        "讲授段落名称",
        "虚拟教师可直接朗读的讲稿",
        "检查题",
        "答案理由",
    }
    if text in placeholders:
        raise CourseDesignError(f"课程蓝图字段仍是占位内容：{field}")
    return text


def _source_pages(value: Any, field: str, allowed_pages: set[int]) -> list[int]:
    if not isinstance(value, list):
        raise CourseDesignError(f"{field}必须是页码数组")
    pages: list[int] = []
    for raw_page in value:
        if isinstance(raw_page, bool):
            continue
        try:
            page = int(raw_page)
        except (TypeError, ValueError):
            continue
        if page in allowed_pages and page not in pages:
            pages.append(page)
    if not pages:
        raise CourseDesignError(f"{field}没有引用所选教材页")
    return sorted(pages)


def _resolve_correct_answer(raw_answer: Any, choices: list[str]) -> str:
    answer = _required_text(
        raw_answer,
        "checkpoint.correct_answer",
        max_length=120,
    )
    if answer in choices:
        return answer
    normalized = answer.strip().upper()
    normalized = normalized.removeprefix("选项").strip()
    normalized = normalized.rstrip(".、：:")
    valid_labels = {chr(ord("A") + index) for index in range(min(len(choices), 26))}
    if normalized in valid_labels:
        prefix = normalized + "."
        prefix_alt = normalized + "、"
        matched = next(
            (
                choice
                for choice in choices
                if choice.strip().upper().startswith((prefix, prefix_alt))
            ),
            None,
        )
        if matched:
            return matched
    raise CourseDesignError("检查题的正确答案不在选项中")


def build_course_source(pages: list[dict[str, Any]]) -> tuple[str, set[int]]:
    if not pages:
        raise CourseDesignError("没有可用于生成课程的教材正文")
    if len(pages) > MAX_COURSE_PAGES:
        raise CourseDesignError(f"课程Demo一次最多使用{MAX_COURSE_PAGES}页")

    chunks: list[str] = []
    allowed_pages: set[int] = set()
    total_chars = 0
    for item in pages:
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text", "")).strip()
        if not text or not bool(item.get("has_text_layer", True)):
            continue
        chunk = f"\n===== 教材PDF第{page_number}页 =====\n{text}"
        if total_chars + len(chunk) > MAX_COURSE_SOURCE_CHARS:
            raise CourseDesignError(
                f"所选正文超过{MAX_COURSE_SOURCE_CHARS}字，请缩小页码范围"
            )
        chunks.append(chunk)
        allowed_pages.add(page_number)
        total_chars += len(chunk)
    if not chunks:
        raise CourseDesignError("所选页面没有可用文字层")
    return "".join(chunks).strip(), allowed_pages


def build_course_design_prompt(
    *,
    filename: str,
    source_text: str,
    audience: str,
    lesson_count: int,
    target_minutes: int,
    required_sections: list[dict[str, Any]] | None = None,
) -> str:
    schema = {
        "course_title": "课程名称",
        "course_description": "课程简介",
        "audience": audience,
        "total_minutes": target_minutes,
        "learning_objectives": ["完成课程后能够……"],
        "lessons": [
            {
                "title": "课时名称",
                "objective": "本课时学习目标",
                "estimated_minutes": 10,
                "source_pages": [23, 24],
                "teaching_blocks": [
                    {
                        "title": "讲授段落名称",
                        "script": "虚拟教师可直接朗读的讲稿",
                        "source_pages": [23],
                    }
                ],
                "checkpoint": {
                    "question": "检查题",
                    "choices": ["A", "B", "C"],
                    "correct_answer": "A",
                    "explanation": "答案理由",
                    "source_pages": [23],
                },
            }
        ],
    }
    schema_json = json.dumps(schema, ensure_ascii=False)
    section_lines = "\n".join(
        f"- {item['title']}（起始于PDF第{item['page_number']}页）"
        for item in (required_sections or [])
    ) or "- 未可靠识别小节标题，请根据正文顺序保留全部主要主题。"
    return f"""你是一名严谨的课程设计师。请仅根据下方教材原文，把选定内容设计成一个可编辑、可追溯的虚拟教师课程蓝图。

教材文件：{Path(filename).name}
目标学习者：{audience}
要求课时数：严格生成{lesson_count}个课时
建议总时长：约{target_minutes}分钟

必须保留的教材结构：
{section_lines}

设计规则：
1. 不得使用原文之外的事实，不得补写教材未出现的公式、结论或数据。
2. 每个课时只覆盖一个清晰主题，并按照由浅入深的顺序组织。
3. 上述“必须保留的教材结构”中的每个小节都必须映射到至少一个课时。可以压缩讲解、例子和推导，但不得压缩掉教材结构。
4. 默认一个主要小节对应一个课时；课时数较少时只允许合并相邻小节，课时数较多时可以拆分内容较长的小节。
5. 每个课时生成2到3个teaching_blocks；script是虚拟教师可直接朗读的中文讲稿，每段120到260字，不使用Markdown。
6. 每个课时只设置1道选择题，choices必须恰好有3个非空且互不重复的完整选项，correct_answer必须与其中一个选项完全一致。
7. 课程、讲稿和题目的source_pages只能填写下方明确出现的PDF页码。页码是PDF文件页码，不是书本印刷页码。
8. source_pages必须真实对应内容出处。若原文不足以支持某项内容，就不要生成该内容。
9. 不要生成欢迎套话、夸张宣传、诊断或治疗建议。
10. JSON结构示例中的“课程名称”“本课时学习目标”等只是字段说明，必须全部替换成根据教材生成的具体内容，禁止原样复制占位词。
11. correct_answer可以填写完整选项，或填写与选项前缀对应的A、B、C。
12. 只输出一个JSON对象，不要输出代码围栏或解释文字。JSON结构为：{schema_json}
13. 输出前逐课时自检：课时数量正确；所有标题和讲稿均已替换占位词；每题恰好有3个不同选项；正确答案存在于选项中；所有页码均来自教材原文。

教材原文如下：
{source_text}
"""


def normalize_course_blueprint(
    data: dict[str, Any],
    *,
    allowed_pages: set[int],
    expected_lesson_count: int,
    default_audience: str,
) -> dict[str, Any]:
    course_title = _specific_text(data.get("course_title"), "course_title", max_length=100)
    description = _specific_text(
        data.get("course_description"), "course_description", max_length=500
    )
    raw_objectives = data.get("learning_objectives")
    if not isinstance(raw_objectives, list):
        raise CourseDesignError("learning_objectives必须是数组")
    objectives = [
        _required_text(item, "learning_objectives", max_length=160)
        for item in raw_objectives[:6]
        if isinstance(item, str) and item.strip()
    ]
    if not objectives:
        raise CourseDesignError("课程蓝图没有学习目标")

    raw_lessons = data.get("lessons")
    if not isinstance(raw_lessons, list) or len(raw_lessons) != expected_lesson_count:
        raise CourseDesignError(
            f"课程蓝图必须包含{expected_lesson_count}个课时"
        )

    lessons: list[dict[str, Any]] = []
    review_notes: list[str] = []
    for lesson_index, raw_lesson in enumerate(raw_lessons, start=1):
        if not isinstance(raw_lesson, dict):
            raise CourseDesignError(f"第{lesson_index}个课时不是JSON对象")
        blocks_raw = raw_lesson.get("teaching_blocks")
        if not isinstance(blocks_raw, list) or not 1 <= len(blocks_raw) <= 4:
            raise CourseDesignError(f"第{lesson_index}个课时讲稿段落数量无效")
        blocks: list[dict[str, Any]] = []
        for block_index, raw_block in enumerate(blocks_raw, start=1):
            if not isinstance(raw_block, dict):
                raise CourseDesignError(
                    f"第{lesson_index}课时第{block_index}段不是JSON对象"
                )
            blocks.append(
                {
                    "title": _specific_text(
                        raw_block.get("title"), "teaching_blocks.title", max_length=80
                    ),
                    "script": _specific_text(
                        raw_block.get("script"), "teaching_blocks.script", max_length=800
                    ),
                    "source_pages": _source_pages(
                        raw_block.get("source_pages"),
                        "teaching_blocks.source_pages",
                        allowed_pages,
                    ),
                }
            )

        checkpoint = raw_lesson.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise CourseDesignError(f"第{lesson_index}个课时缺少检查题")
        choices_raw = checkpoint.get("choices")
        if not isinstance(choices_raw, list):
            raise CourseDesignError(f"第{lesson_index}个课时选项必须是数组")
        choices = [
            _required_text(choice, "checkpoint.choices", max_length=120)
            for choice in choices_raw
            if isinstance(choice, str) and choice.strip()
        ]
        if len(choices) != 3 or len(set(choices)) != 3:
            raise CourseDesignError(f"第{lesson_index}个课时必须有3个不同选项")
        correct_answer = _resolve_correct_answer(
            checkpoint.get("correct_answer"), choices
        )
        try:
            estimated_minutes = int(raw_lesson.get("estimated_minutes", 10))
        except (TypeError, ValueError):
            estimated_minutes = 10
        lesson_title = _specific_text(
            raw_lesson.get("title"), "lessons.title", max_length=100
        )
        raw_objective = str(raw_lesson.get("objective", "")).strip()
        if raw_objective == "本课时学习目标":
            objective_topic = lesson_title.split("：", 1)[-1].strip()
            lesson_objective = f"理解并能够说明{objective_topic}的核心概念、方法与适用条件。"
            review_notes.append(
                f"第{lesson_index}课时的目标字段由系统根据课时标题补全，请人工确认。"
            )
        else:
            lesson_objective = _specific_text(
                raw_lesson.get("objective"), "lessons.objective", max_length=240
            )
        lessons.append(
            {
                "title": lesson_title,
                "objective": lesson_objective,
                "estimated_minutes": min(60, max(3, estimated_minutes)),
                "source_pages": _source_pages(
                    raw_lesson.get("source_pages"),
                    "lessons.source_pages",
                    allowed_pages,
                ),
                "teaching_blocks": blocks,
                "checkpoint": {
                    "question": _specific_text(
                        checkpoint.get("question"), "checkpoint.question", max_length=300
                    ),
                    "choices": choices,
                    "correct_answer": correct_answer,
                    "explanation": _specific_text(
                        checkpoint.get("explanation"),
                        "checkpoint.explanation",
                        max_length=500,
                    ),
                    "source_pages": _source_pages(
                        checkpoint.get("source_pages"),
                        "checkpoint.source_pages",
                        allowed_pages,
                    ),
                },
            }
        )

    covered_pages: set[int] = set()
    for lesson in lessons:
        covered_pages.update(lesson["source_pages"])
        for block in lesson["teaching_blocks"]:
            covered_pages.update(block["source_pages"])
        covered_pages.update(lesson["checkpoint"]["source_pages"])
    uncovered_pages = allowed_pages - covered_pages
    coverage_ratio = len(covered_pages) / max(1, len(allowed_pages))
    if coverage_ratio < 0.65:
        review_notes.append(
            "当前讲稿引用页码覆盖不足65%，可能遗漏章节后半部分或重要小节；建议增加课时数后重新生成。"
        )

    try:
        total_minutes = int(data.get("total_minutes", sum(item["estimated_minutes"] for item in lessons)))
    except (TypeError, ValueError):
        total_minutes = sum(item["estimated_minutes"] for item in lessons)
    return {
        "course_title": course_title,
        "course_description": description,
        "audience": str(data.get("audience") or default_audience).strip()[:100],
        "total_minutes": min(240, max(5, total_minutes)),
        "learning_objectives": objectives,
        "lessons": lessons,
        "status": "draft",
        "grounding": {
            "source_page_count": len(allowed_pages),
            "source_pages": sorted(allowed_pages),
            "covered_pages": sorted(covered_pages),
            "uncovered_pages": sorted(uncovered_pages),
            "coverage_ratio": round(coverage_ratio, 4),
            "page_references_validated": True,
            "human_review_required": True,
        },
        "review_notes": review_notes,
    }


def recover_editable_course_blueprint(
    data: dict[str, Any],
    *,
    allowed_pages: set[int],
    expected_lesson_count: int,
    default_audience: str,
) -> dict[str, Any]:
    """Keep a mostly valid model response editable instead of discarding it.

    This recovery path deliberately remains strict about structure and source
    page references, because the current editor cannot safely repair those.
    Text placeholders, empty editable text, duplicated choices, and an invalid
    correct answer are retained and reported for manual correction.
    """

    issues: list[dict[str, Any]] = []
    auto_fixes: list[str] = []
    placeholders = {
        "课程名称",
        "课程简介",
        "课时名称",
        "本课时学习目标",
        "讲授段落名称",
        "虚拟教师可直接朗读的讲稿",
        "检查题",
        "答案理由",
    }

    def editable_text(
        value: Any,
        path: str,
        *,
        max_length: int,
        lesson_index: int | None = None,
        block_index: int | None = None,
    ) -> str:
        text = value.strip()[:max_length] if isinstance(value, str) else ""
        if not text:
            issues.append(
                {
                    "path": path,
                    "message": "内容为空，请手动补充",
                    "lesson_index": lesson_index,
                    "block_index": block_index,
                }
            )
        elif text in placeholders:
            issues.append(
                {
                    "path": path,
                    "message": f"“{text}”仍是示例占位词，请替换为具体内容",
                    "lesson_index": lesson_index,
                    "block_index": block_index,
                }
            )
        return text

    raw_lessons = data.get("lessons")
    if not isinstance(raw_lessons, list) or len(raw_lessons) != expected_lesson_count:
        raise CourseDesignError(
            f"课程蓝图必须包含{expected_lesson_count}个课时，当前结构无法在编辑器中安全恢复"
        )

    course_title = editable_text(data.get("course_title"), "course_title", max_length=100)
    description = editable_text(
        data.get("course_description"), "course_description", max_length=500
    )
    raw_objectives = data.get("learning_objectives")
    if not isinstance(raw_objectives, list):
        raise CourseDesignError("learning_objectives结构无效，当前无法恢复为可编辑草稿")
    objectives = [
        editable_text(item, f"learning_objectives[{index}]", max_length=160)
        for index, item in enumerate(raw_objectives[:6])
    ]
    if not objectives:
        issues.append(
            {
                "path": "learning_objectives",
                "message": "缺少学习目标；当前编辑器无法新增目标，请重新生成",
                "lesson_index": None,
                "block_index": None,
            }
        )
        objectives = [""]

    lessons: list[dict[str, Any]] = []
    for lesson_index, raw_lesson in enumerate(raw_lessons):
        display_index = lesson_index + 1
        if not isinstance(raw_lesson, dict):
            raise CourseDesignError(f"第{display_index}个课时不是JSON对象，无法恢复")
        lesson_title = editable_text(
            raw_lesson.get("title"),
            f"lessons[{lesson_index}].title",
            max_length=100,
            lesson_index=lesson_index,
        )
        blocks_raw = raw_lesson.get("teaching_blocks")
        if not isinstance(blocks_raw, list):
            raise CourseDesignError(
                f"第{display_index}个课时讲稿段落结构无效，无法在当前编辑器中恢复"
            )
        cleaned_blocks: list[Any] = []
        for raw_block in blocks_raw:
            if (
                isinstance(raw_block, dict)
                and str(raw_block.get("title", "")).strip() == "检查题"
                and not str(raw_block.get("script", "")).strip()
            ):
                auto_fixes.append(
                    f"第{display_index}课时已移除误放在讲稿列表中的空检查题段落"
                )
                continue
            cleaned_blocks.append(raw_block)
        blocks_raw = cleaned_blocks
        if not 1 <= len(blocks_raw) <= 4:
            raise CourseDesignError(
                f"第{display_index}个课时讲稿段落结构无效，无法在当前编辑器中恢复"
            )
        blocks: list[dict[str, Any]] = []
        for block_index, raw_block in enumerate(blocks_raw):
            if not isinstance(raw_block, dict):
                raise CourseDesignError(
                    f"第{display_index}课时第{block_index + 1}段不是JSON对象，无法恢复"
                )
            block_path = f"lessons[{lesson_index}].teaching_blocks[{block_index}]"
            raw_block_title = str(raw_block.get("title", "")).strip()
            if raw_block_title == "讲授段落名称":
                raw_block_title = (
                    f"{lesson_title or f'第{display_index}课时'} · 第{block_index + 1}部分"
                )
                auto_fixes.append(
                    f"第{display_index}课时第{block_index + 1}段标题已替换占位词"
                )
            blocks.append(
                {
                    "title": editable_text(
                        raw_block_title,
                        f"{block_path}.title",
                        max_length=80,
                        lesson_index=lesson_index,
                        block_index=block_index,
                    ),
                    "script": editable_text(
                        raw_block.get("script"),
                        f"{block_path}.script",
                        max_length=800,
                        lesson_index=lesson_index,
                        block_index=block_index,
                    ),
                    "source_pages": _source_pages(
                        raw_block.get("source_pages"),
                        f"第{display_index}课时第{block_index + 1}段source_pages",
                        allowed_pages,
                    ),
                }
            )

        checkpoint = raw_lesson.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise CourseDesignError(f"第{display_index}个课时缺少检查题，无法恢复")
        checkpoint_path = f"lessons[{lesson_index}].checkpoint"
        raw_choices = checkpoint.get("choices")
        if not isinstance(raw_choices, list):
            raw_choices = []
        all_choices = [
            str(choice).strip()[:120]
            for choice in raw_choices
            if isinstance(choice, str) and str(choice).strip()
        ]
        raw_answer = str(checkpoint.get("correct_answer", "")).strip()[:120]
        if len(all_choices) > 3:
            try:
                resolved_answer = _resolve_correct_answer(raw_answer, all_choices)
            except CourseDesignError:
                resolved_answer = ""
            retained = all_choices[:3]
            if resolved_answer and resolved_answer not in retained:
                retained = [*all_choices[:2], resolved_answer]
            choices = retained
            if resolved_answer:
                raw_answer = resolved_answer
            auto_fixes.append(
                f"第{display_index}课时检查题已从{len(all_choices)}个选项精简为3个，并保留正确答案"
            )
        else:
            choices = all_choices
        choices.extend([""] * (3 - len(choices)))
        if any(not choice for choice in choices) or len(set(choices)) != 3:
            issues.append(
                {
                    "path": f"{checkpoint_path}.choices",
                    "message": "检查题需要3个非空且互不重复的选项",
                    "lesson_index": lesson_index,
                    "block_index": None,
                }
            )
        try:
            correct_answer = _resolve_correct_answer(raw_answer, choices)
        except CourseDesignError:
            correct_answer = raw_answer
            issues.append(
                {
                    "path": f"{checkpoint_path}.correct_answer",
                    "message": "正确答案必须选择上方3个选项之一",
                    "lesson_index": lesson_index,
                    "block_index": None,
                }
            )
        try:
            estimated_minutes = int(raw_lesson.get("estimated_minutes", 10))
        except (TypeError, ValueError):
            estimated_minutes = 10
        raw_objective = str(raw_lesson.get("objective", "")).strip()
        if raw_objective == "本课时学习目标" and lesson_title:
            raw_objective = f"理解并能够说明{lesson_title}的核心概念、方法与适用条件。"
            auto_fixes.append(f"第{display_index}课时学习目标已根据课时标题补全")
        lessons.append(
            {
                "title": lesson_title,
                "objective": editable_text(
                    raw_objective,
                    f"lessons[{lesson_index}].objective",
                    max_length=240,
                    lesson_index=lesson_index,
                ),
                "estimated_minutes": min(60, max(3, estimated_minutes)),
                "source_pages": _source_pages(
                    raw_lesson.get("source_pages"),
                    f"第{display_index}课时source_pages",
                    allowed_pages,
                ),
                "teaching_blocks": blocks,
                "checkpoint": {
                    "question": editable_text(
                        checkpoint.get("question"),
                        f"{checkpoint_path}.question",
                        max_length=300,
                        lesson_index=lesson_index,
                    ),
                    "choices": choices,
                    "correct_answer": correct_answer,
                    "explanation": editable_text(
                        checkpoint.get("explanation"),
                        f"{checkpoint_path}.explanation",
                        max_length=500,
                        lesson_index=lesson_index,
                    ),
                    "source_pages": _source_pages(
                        checkpoint.get("source_pages"),
                        f"第{display_index}课时检查题source_pages",
                        allowed_pages,
                    ),
                },
            }
        )

    covered_pages: set[int] = set()
    for lesson in lessons:
        covered_pages.update(lesson["source_pages"])
        for block in lesson["teaching_blocks"]:
            covered_pages.update(block["source_pages"])
        covered_pages.update(lesson["checkpoint"]["source_pages"])
    uncovered_pages = allowed_pages - covered_pages
    try:
        total_minutes = int(
            data.get(
                "total_minutes",
                sum(item["estimated_minutes"] for item in lessons),
            )
        )
    except (TypeError, ValueError):
        total_minutes = sum(item["estimated_minutes"] for item in lessons)
    review_notes = []
    if issues:
        review_notes.append(
            "模型返回内容未完全通过质量校验，系统已保留为待修复草稿；请修改标红字段后再发布。"
        )
    if auto_fixes:
        review_notes.append("系统已进行安全的格式修复：" + "；".join(auto_fixes) + "。")
    review_notes.extend(
        str(item).strip()
        for item in data.get("review_notes", [])
        if isinstance(item, str) and item.strip()
    )
    return {
        "course_title": course_title,
        "course_description": description,
        "audience": str(data.get("audience") or default_audience).strip()[:100],
        "total_minutes": min(240, max(5, total_minutes)),
        "learning_objectives": objectives,
        "lessons": lessons,
        "status": "draft",
        "quality_status": "needs_fix" if issues else "auto_fixed",
        "validation_issues": issues,
        "auto_fixes": auto_fixes,
        "grounding": {
            "source_page_count": len(allowed_pages),
            "source_pages": sorted(allowed_pages),
            "covered_pages": sorted(covered_pages),
            "uncovered_pages": sorted(uncovered_pages),
            "coverage_ratio": round(len(covered_pages) / max(1, len(allowed_pages)), 4),
            "page_references_validated": True,
            "human_review_required": True,
        },
        "review_notes": review_notes,
    }


class QwenCourseDesigner:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        debug: bool = False,
        log_dir: Path | None = None,
    ):
        self.llm = QwenTeachingLLM(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=120,
            debug=debug,
            log_dir=log_dir,
        )
        self.model = model

    def design(
        self,
        *,
        filename: str,
        pages: list[dict[str, Any]],
        audience: str,
        lesson_count: int,
        target_minutes: int,
    ) -> dict[str, Any]:
        source_text, allowed_pages = build_course_source(pages)
        prompt = build_course_design_prompt(
            filename=filename,
            source_text=source_text,
            audience=audience,
            lesson_count=lesson_count,
            target_minutes=target_minutes,
            required_sections=teachable_sections_from_pages(pages),
        )
        try:
            data = self.llm._complete_json(
                operation="design_course_blueprint",
                system_prompt=prompt,
                recent_messages=[],
                temperature=0.1,
            )
        except (LLMProviderError, LLMResponseFormatError):
            raise
        try:
            blueprint = normalize_course_blueprint(
                data,
                allowed_pages=allowed_pages,
                expected_lesson_count=lesson_count,
                default_audience=audience,
            )
            blueprint["quality_status"] = "valid"
            blueprint["validation_issues"] = []
            blueprint["auto_fixes"] = []
        except CourseDesignError as strict_error:
            self.llm.trace.write(
                {
                    "operation": "design_course_blueprint_validation",
                    "context": {
                        "filename": Path(filename).name,
                        "expected_lesson_count": lesson_count,
                        "allowed_pages": sorted(allowed_pages),
                    },
                    "error": {
                        "type": type(strict_error).__name__,
                        "message": str(strict_error),
                    },
                }
            )
            try:
                blueprint = recover_editable_course_blueprint(
                    data,
                    allowed_pages=allowed_pages,
                    expected_lesson_count=lesson_count,
                    default_audience=audience,
                )
            except CourseDesignError as recovery_error:
                raise CourseDesignError(
                    f"{strict_error}；且无法保留为可编辑草稿：{recovery_error}"
                ) from recovery_error
        blueprint["generator"] = {"provider": "qwen", "model": self.model}
        return blueprint


def split_course_page_batches(
    pages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Keep source pages intact while fitting each model request."""
    valid_pages = [
        page
        for page in pages
        if bool(page.get("has_text_layer", True)) and str(page.get("text", "")).strip()
    ]
    if not valid_pages:
        raise CourseDesignError("所选章节没有可用于生成课程的正文")
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for page in valid_pages:
        page_chars = len(str(page.get("text", ""))) + 40
        if page_chars > MAX_COURSE_SOURCE_CHARS:
            raise CourseDesignError(f"PDF第{page.get('page_number')}页文字量异常，请人工检查")
        would_overflow = current and (
            len(current) >= MAX_COURSE_PAGES
            or current_chars + page_chars > MAX_COURSE_SOURCE_CHARS
        )
        if would_overflow:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(page)
        current_chars += page_chars
    if current:
        batches.append(current)
    if len(batches) > MAX_CHAPTER_BATCHES:
        raise CourseDesignError(
            f"章节需要拆成{len(batches)}批，超过当前上限{MAX_CHAPTER_BATCHES}批"
        )
    return batches


def chapter_generation_plan(
    pages: list[dict[str, Any]], *, requested_lessons: int
) -> dict[str, Any]:
    batches = split_course_page_batches(pages)
    effective_lessons = max(requested_lessons, len(batches))
    page_counts = [len(batch) for batch in batches]
    char_counts = [sum(len(str(page.get("text", ""))) for page in batch) for batch in batches]
    detected_sections = teachable_sections_from_pages(pages)
    recommended_lessons = min(12, len(detected_sections)) if detected_sections else min(
        12,
        max(
            len(batches),
            math.ceil(sum(page_counts) / 5),
            math.ceil(sum(char_counts) / 5_000),
        ),
    )
    lesson_counts = [1 for _batch in batches]
    remaining = effective_lessons - len(batches)
    while remaining > 0:
        candidates = sorted(
            range(len(batches)),
            key=lambda index: char_counts[index] / lesson_counts[index],
            reverse=True,
        )
        lesson_counts[candidates[0]] += 1
        remaining -= 1
    return {
        "batch_count": len(batches),
        "page_counts": page_counts,
        "character_counts": char_counts,
        "lesson_counts": lesson_counts,
        "effective_lesson_count": effective_lessons,
        "recommended_lesson_count": recommended_lessons,
        "detected_sections": detected_sections,
        "estimated_model_calls": len(batches),
    }


def design_chapter_in_batches(
    designer: Any,
    *,
    filename: str,
    chapter_title: str,
    pages: list[dict[str, Any]],
    audience: str,
    lesson_count: int,
    target_minutes: int,
) -> dict[str, Any]:
    batches = split_course_page_batches(pages)
    plan = chapter_generation_plan(pages, requested_lessons=lesson_count)
    total_chars = max(1, sum(plan["character_counts"]))
    blueprints: list[dict[str, Any]] = []
    for index, batch in enumerate(batches):
        batch_minutes = max(
            10,
            round(target_minutes * plan["character_counts"][index] / total_chars),
        )
        batch_filename = f"{Path(filename).stem} · {chapter_title} · 第{index + 1}/{len(batches)}批.pdf"
        try:
            blueprint = designer.design(
                filename=batch_filename,
                pages=batch,
                audience=audience,
                lesson_count=plan["lesson_counts"][index],
                target_minutes=batch_minutes,
            )
        except LLMResponseFormatError as exc:
            raise LLMResponseFormatError(
                _batch_failure_message(index, len(batches), str(exc))
            ) from exc
        except LLMProviderError as exc:
            raise LLMProviderError(
                _batch_failure_message(index, len(batches), str(exc))
            ) from exc
        except CourseDesignError as exc:
            raise CourseDesignError(
                _batch_failure_message(index, len(batches), str(exc))
            ) from exc
        blueprints.append(blueprint)

    lessons = [
        lesson
        for blueprint in blueprints
        for lesson in blueprint.get("lessons", [])
    ]
    objectives: list[str] = []
    review_notes: list[str] = []
    validation_issues: list[dict[str, Any]] = []
    auto_fixes: list[str] = []
    source_pages: set[int] = set()
    lesson_offset = 0
    for blueprint in blueprints:
        for objective in blueprint.get("learning_objectives", []):
            if objective not in objectives:
                objectives.append(objective)
        review_notes.extend(blueprint.get("review_notes", []))
        for raw_issue in blueprint.get("validation_issues", []):
            issue = dict(raw_issue)
            if isinstance(issue.get("lesson_index"), int):
                issue["lesson_index"] += lesson_offset
            validation_issues.append(issue)
        auto_fixes.extend(str(item) for item in blueprint.get("auto_fixes", []))
        source_pages.update(blueprint.get("grounding", {}).get("source_pages", []))
        lesson_offset += len(blueprint.get("lessons", []))
    if len(batches) > 1:
        review_notes.append(
            f"本章正文分为{len(batches)}批调用模型后自动合并，请重点检查相邻课时是否重复或跳跃。"
        )
    covered_pages: set[int] = set()
    for lesson in lessons:
        covered_pages.update(lesson.get("source_pages", []))
        for block in lesson.get("teaching_blocks", []):
            covered_pages.update(block.get("source_pages", []))
        covered_pages.update(lesson.get("checkpoint", {}).get("source_pages", []))
    uncovered_pages = source_pages - covered_pages
    coverage_ratio = len(covered_pages) / max(1, len(source_pages))
    if coverage_ratio < 0.65 and not any("覆盖不足65%" in note for note in review_notes):
        review_notes.append(
            "当前讲稿引用页码覆盖不足65%，可能遗漏章节后半部分或重要小节；建议增加课时数后重新生成。"
        )
    model = str(blueprints[0].get("generator", {}).get("model", "unknown"))
    return {
        "course_title": f"{chapter_title}课程",
        "course_description": f"根据教材“{chapter_title}”生成的可追溯课程草稿。",
        "audience": audience,
        "total_minutes": sum(int(item.get("estimated_minutes", 0)) for item in lessons),
        "learning_objectives": objectives[:10],
        "lessons": lessons,
        "status": "draft",
        "quality_status": "needs_fix" if validation_issues else (
            "auto_fixed" if auto_fixes else "valid"
        ),
        "validation_issues": validation_issues,
        "auto_fixes": auto_fixes,
        "grounding": {
            "source_page_count": len(source_pages),
            "source_pages": sorted(source_pages),
            "covered_pages": sorted(covered_pages),
            "uncovered_pages": sorted(uncovered_pages),
            "coverage_ratio": round(coverage_ratio, 4),
            "page_references_validated": True,
            "human_review_required": True,
        },
        "review_notes": review_notes,
        "generator": {
            "provider": "qwen",
            "model": model,
            "model_calls": len(batches),
            "batch_count": len(batches),
        },
        "generation_plan": plan,
    }


def _batch_failure_message(index: int, batch_count: int, reason: str) -> str:
    batch_number = index + 1
    if index:
        progress = f"此前{index}批已返回，但整份草稿尚未保存"
    else:
        progress = "整份草稿尚未保存"
    return (
        f"第{batch_number}/{batch_count}批生成失败：{reason}；{progress}。"
        f"截至失败处可能已发起{batch_number}次模型调用，手动重试会重新计费。"
    )
