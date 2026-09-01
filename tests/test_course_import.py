from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.course_import import (
    CourseImportError,
    clean_page_text,
    detect_headings,
    inspect_pdf_bytes,
    preview_pdf_bytes,
)
from app.course_import_store import CourseImportStore
from app.rag import TextbookRAGStore
from app.api import app


def _text_pdf() -> bytes:
    return _pages_pdf(
        [["2.1 Experience Error and Overfitting", "This page contains enough text for preview and course import testing."]]
    )


def _pages_pdf(pages: list[list[str]]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        commands: list[bytes] = []
        for index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(
                f"BT /F1 12 Tf 72 {720 - index * 30} Td ({escaped}) Tj ET".encode("ascii")
            )
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _blank_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _reviewed_blueprint() -> dict:
    return {
        "course_title": "测试教材第一章课程",
        "course_description": "依据测试教材第一章整理的确定性课程。",
        "audience": "本科生",
        "total_minutes": 12,
        "learning_objectives": ["理解测试章节的核心概念"],
        "status": "draft",
        "grounding": {
            "source_page_count": 2,
            "source_pages": [1, 2],
            "page_references_validated": True,
            "human_review_required": True,
        },
        "generator": {"provider": "fake", "model": "fake-model"},
        "review_notes": [],
        "lessons": [
            {
                "title": "认识测试概念",
                "objective": "能够解释测试概念及其基本作用",
                "estimated_minutes": 12,
                "source_pages": [1, 2],
                "teaching_blocks": [
                    {
                        "title": "核心讲解",
                        "script": "这一段是经过人工审核的固定讲稿，用于验证课程发布后不再调用语言模型。",
                        "source_pages": [1],
                    }
                ],
                "checkpoint": {
                    "question": "下面哪个选项符合本课内容？",
                    "choices": ["正确选项", "干扰项一", "干扰项二"],
                    "correct_answer": "正确选项",
                    "explanation": "正确选项与教材第一页的讲解一致。",
                    "source_pages": [1],
                },
            }
        ],
    }


def _bookmarked_pdf() -> bytes:
    writer = PdfWriter()
    source = PdfReader(BytesIO(_text_pdf()))
    for _ in range(5):
        writer.add_page(source.pages[0])
    writer.add_outline_item("第1章 绪论", 0)
    writer.add_outline_item("第2章 方法", 2)
    writer.add_outline_item("附录", 4)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class CourseImportTests(unittest.TestCase):
    def test_detects_section_heading_when_pdf_inserts_spaces(self):
        headings = detect_headings("3 .4线性判别分析", 8)
        self.assertEqual(headings[0]["title"], "3.4 线性判别分析")

    def test_cleans_page_numbers_but_keeps_headings(self):
        cleaned = clean_page_text(" 23 \n2.1 经验误差与过拟合\n  正文内容  ")
        self.assertNotIn("23", cleaned)
        self.assertIn("2.1 经验误差与过拟合", cleaned)

    def test_detects_chapter_and_section_headings(self):
        headings = detect_headings(
            "第 2 章 模型评估与选择\n2.1 经验误差与过拟合",
            23,
        )
        self.assertEqual(headings[0]["level"], 1)
        self.assertEqual(headings[0]["page_number"], 23)
        self.assertTrue(any(item["title"].startswith("2.1") for item in headings))

    def test_previews_only_requested_text_pages(self):
        result = preview_pdf_bytes(
            _text_pdf(),
            filename="sample.pdf",
            start_page=1,
            end_page=1,
        )
        self.assertEqual(result["total_pages"], 1)
        self.assertEqual(result["text_layer_pages"], 1)
        self.assertFalse(result["ocr_used"])
        self.assertIn("Experience Error", result["pages"][0]["text"])

    def test_rejects_invalid_pdf(self):
        with self.assertRaisesRegex(CourseImportError, "有效PDF"):
            preview_pdf_bytes(
                b"not a pdf",
                filename="bad.pdf",
                start_page=1,
                end_page=1,
            )

    def test_inspects_full_pdf_chapters_from_top_level_bookmarks(self):
        result = inspect_pdf_bytes(_bookmarked_pdf(), filename="book.pdf")
        self.assertEqual(result["chapter_detection"], "pdf_bookmark")
        self.assertEqual(len(result["chapters"]), 2)
        self.assertEqual(result["chapters"][0]["start_page"], 1)
        self.assertEqual(result["chapters"][0]["end_page"], 2)
        self.assertEqual(result["chapters"][1]["start_page"], 3)
        self.assertEqual(result["chapters"][1]["end_page"], 4)

    def test_infers_chapters_from_text_headings_without_bookmarks(self):
        payload = _pages_pdf(
            [
                ["Chapter 1 Foundations", "This page introduces the foundations with enough body text for detection."],
                ["Ordinary explanatory material", "This page continues the first chapter with enough body text."],
                ["Chapter 2 Methods", "This page introduces methods with enough body text for detection."],
                ["Ordinary explanatory material", "This page continues the second chapter with enough body text."],
            ]
        )
        result = inspect_pdf_bytes(payload, filename="no-bookmarks.pdf")
        self.assertEqual(result["chapter_detection"], "text_heading")
        self.assertEqual(len(result["chapters"]), 2)
        self.assertEqual(result["chapters"][0]["start_page"], 1)
        self.assertEqual(result["chapters"][0]["end_page"], 2)
        self.assertEqual(result["chapters"][1]["start_page"], 3)
        self.assertFalse(result["requires_ocr"])

    def test_infers_numbered_modules_when_no_explicit_chapter_headings(self):
        payload = _pages_pdf(
            [
                ["1. Foundations", "This page contains enough ordinary body text for local structure detection."],
                ["Ordinary explanatory material", "This page continues the first numbered module with more body text."],
                ["2. Methods", "This page contains enough ordinary body text for local structure detection."],
            ]
        )
        result = inspect_pdf_bytes(payload, filename="numbered.pdf")
        self.assertEqual(result["chapter_detection"], "numbered_heading")
        self.assertEqual([item["start_page"] for item in result["chapters"]], [1, 3])

    def test_falls_back_to_fixed_page_windows_without_structure(self):
        payload = _pages_pdf(
            [
                [
                    "Ordinary explanatory material",
                    "This page has enough body text but intentionally has no chapter or numbered heading.",
                ]
                for _ in range(61)
            ]
        )
        result = inspect_pdf_bytes(payload, filename="unstructured.pdf")
        self.assertEqual(result["chapter_detection"], "page_window")
        self.assertEqual(
            [(item["start_page"], item["end_page"]) for item in result["chapters"]],
            [(1, 30), (31, 60), (61, 61)],
        )
        self.assertFalse(result["requires_ocr"])

    def test_marks_image_only_pdf_as_requiring_ocr(self):
        result = inspect_pdf_bytes(_blank_pdf(2), filename="scan.pdf")
        self.assertEqual(result["chapter_detection"], "page_window")
        self.assertTrue(result["requires_ocr"])
        self.assertEqual(result["scanned_text_layer_pages"], 0)

    def test_store_deduplicates_same_full_pdf_and_persists_metadata(self):
        with TemporaryDirectory() as directory:
            store = CourseImportStore(Path(directory))
            first = store.create(_bookmarked_pdf(), filename="book.pdf")
            second = store.create(_bookmarked_pdf(), filename="renamed.pdf")
            self.assertEqual(first["import_id"], second["import_id"])
            self.assertEqual(second["schema_version"], 2)
            restored = store.get(first["import_id"])
            self.assertEqual(restored["total_pages"], 5)
            self.assertTrue(store.source_path(first["import_id"]).is_file())
            saved = store.save_chapter_blueprint(
                first["import_id"],
                1,
                {"course_title": "测试课程", "lessons": [{"title": "第一课"}]},
            )
            self.assertTrue(saved["draft"]["stored_locally"])
            self.assertEqual(store.get(first["import_id"])["chapter_drafts"][0]["lesson_count"], 1)

    def test_manual_chapter_edit_marks_affected_draft_stale(self):
        with TemporaryDirectory() as directory:
            store = CourseImportStore(Path(directory))
            created = store.create(_bookmarked_pdf(), filename="book.pdf")
            store.save_chapter_blueprint(created["import_id"], 1, _reviewed_blueprint())
            updated = store.replace_chapters(
                created["import_id"],
                [
                    {"chapter_index": 1, "title": "第一章（人工）", "start_page": 1, "end_page": 1},
                    {"chapter_index": 2, "title": "第二章（人工）", "start_page": 2, "end_page": 4},
                ],
            )
            self.assertEqual(updated["chapter_detection"], "manual")
            self.assertEqual(updated["chapters"][1]["page_count"], 3)
            self.assertTrue(updated["chapter_drafts"][0]["stale"])
            with self.assertRaisesRegex(CourseImportError, "重新生成"):
                store.get_chapter_draft(created["import_id"], 1)

    def test_manual_chapter_edit_rejects_overlapping_ranges(self):
        with TemporaryDirectory() as directory:
            store = CourseImportStore(Path(directory))
            created = store.create(_bookmarked_pdf(), filename="book.pdf")
            with self.assertRaisesRegex(CourseImportError, "不能重叠"):
                store.replace_chapters(
                    created["import_id"],
                    [
                        {"chapter_index": 1, "title": "第一章", "start_page": 1, "end_page": 3},
                        {"chapter_index": 2, "title": "第二章", "start_page": 3, "end_page": 4},
                    ],
                )

    def test_full_upload_and_chapter_preview_api(self):
        class FakeChapterDesigner:
            def design(self, **kwargs):
                source_pages = [page["page_number"] for page in kwargs["pages"]]
                return {
                    "learning_objectives": ["理解测试章节"],
                    "lessons": [
                        {
                            "title": f"测试课时{index + 1}",
                            "objective": "理解教材内容",
                            "estimated_minutes": 10,
                            "source_pages": source_pages,
                            "teaching_blocks": [],
                            "checkpoint": {},
                        }
                        for index in range(kwargs["lesson_count"])
                    ],
                    "grounding": {"source_pages": source_pages},
                    "review_notes": [],
                    "generator": {"provider": "fake", "model": "fake-model"},
                }

        with TemporaryDirectory() as directory, TestClient(app) as client:
            client.app.state.course_imports = CourseImportStore(Path(directory))
            client.app.state.course_designer = FakeChapterDesigner()
            created = client.post(
                "/v1/course-imports?filename=book.pdf",
                content=_bookmarked_pdf(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(created.status_code, 200)
            import_id = created.json()["import_id"]
            preview = client.post(
                f"/v1/course-imports/{import_id}/chapters/1/preview?lesson_count=2"
            )
            self.assertEqual(preview.status_code, 200)
            payload = preview.json()
            self.assertEqual(payload["chapter"]["title"], "第1章 绪论")
            self.assertEqual(payload["generation_plan"]["estimated_model_calls"], 1)
            designed = client.post(
                f"/v1/course-imports/{import_id}/chapters/1/design",
                json={
                    "audience": "本科生",
                    "lesson_count": 2,
                    "target_minutes": 20,
                },
            )
            self.assertEqual(designed.status_code, 200)
            self.assertEqual(len(designed.json()["lessons"]), 2)
            self.assertEqual(designed.json()["generator"]["model_calls"], 1)
            self.assertTrue(designed.json()["draft"]["stored_locally"])
            restored = client.get(
                f"/v1/course-imports/{import_id}/chapters/1/draft"
            )
            self.assertEqual(restored.status_code, 200)
            self.assertEqual(restored.json()["course_title"], designed.json()["course_title"])
            self.assertTrue(restored.json()["draft"]["stored_locally"])

    def test_reviewed_draft_can_be_published_without_model_call(self):
        with TemporaryDirectory() as directory, TestClient(app) as client:
            store = CourseImportStore(Path(directory))
            client.app.state.course_imports = store
            created = store.create(_bookmarked_pdf(), filename="book.pdf")
            store.save_chapter_blueprint(
                created["import_id"], 1, _reviewed_blueprint()
            )
            response = client.post(
                f"/v1/course-imports/{created['import_id']}/chapters/1/publish",
                json={"blueprint": _reviewed_blueprint()},
            )
            self.assertEqual(response.status_code, 200, response.text)
            course = response.json()["course"]
            self.assertEqual(course["mode"], "guided")
            self.assertFalse(course["built_in"])
            courses = client.get("/v1/courses").json()
            self.assertTrue(
                any(item["lesson_id"] == course["lesson_id"] for item in courses)
            )
            self.assertEqual(len(store.published_course_records()), 1)

            restored = store.get(created["import_id"])
            self.assertEqual(
                restored["chapter_publications"][0]["lesson_id"],
                course["lesson_id"],
            )
            removed = client.delete(
                f"/v1/course-imports/{created['import_id']}/chapters/1/publish"
            )
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertTrue(removed.json()["draft_preserved"])
            self.assertEqual(store.published_course_records(), [])
            self.assertEqual(store.get(created["import_id"])["chapter_publications"], [])
            self.assertEqual(
                store.get_chapter_blueprint(created["import_id"], 1)["status"],
                "draft",
            )
            self.assertFalse(
                any(
                    item["lesson_id"] == course["lesson_id"]
                    for item in client.get("/v1/courses").json()
                )
            )
            projects = client.get("/v1/course-projects")
            self.assertEqual(projects.status_code, 200)
            self.assertEqual(len(projects.json()), 1)
            self.assertFalse(projects.json()[0]["published"])
            deleted = client.delete(
                f"/v1/course-projects/{created['import_id']}/chapters/1"
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertTrue(deleted.json()["draft_removed"])
            self.assertTrue(deleted.json()["textbook_preserved"])
            self.assertTrue(store.source_path(created["import_id"]).is_file())
            self.assertEqual(client.get("/v1/course-projects").json(), [])

    def test_rag_index_and_search_api_do_not_require_an_llm(self):
        with TemporaryDirectory() as directory, TestClient(app) as client:
            store = CourseImportStore(Path(directory) / "imports")
            client.app.state.course_imports = store
            client.app.state.rag = TextbookRAGStore(Path(directory) / "rag.sqlite3")
            created = store.create(_text_pdf(), filename="book.pdf")
            import_id = created["import_id"]

            before = client.get(f"/v1/course-imports/{import_id}/rag/status")
            indexed = client.post(f"/v1/course-imports/{import_id}/rag/index")
            searched = client.post(
                f"/v1/course-imports/{import_id}/rag/search",
                json={"query": "overfitting", "top_k": 3},
            )

            self.assertEqual(before.status_code, 200)
            self.assertFalse(before.json()["indexed"])
            self.assertEqual(indexed.status_code, 200, indexed.text)
            self.assertTrue(indexed.json()["indexed"])
            self.assertEqual(searched.status_code, 200, searched.text)
            self.assertEqual(searched.json()["results"][0]["page_number"], 1)


if __name__ == "__main__":
    unittest.main()
