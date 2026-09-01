from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.course_import import CourseImportError, inspect_pdf_bytes, preview_pdf_bytes


_IMPORT_ID_RE = re.compile(r"^[0-9a-f]{20}$")
MAX_STORED_CHAPTER_PAGES = 160


class CourseImportStore:
    """Local persisted source PDFs; the directory is excluded from Git."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _directory(self, import_id: str) -> Path:
        if not _IMPORT_ID_RE.fullmatch(import_id):
            raise CourseImportError("教材导入ID无效")
        return self.root / import_id

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def _read_metadata(self, import_id: str) -> dict[str, Any]:
        metadata_path = self._directory(import_id) / "metadata.json"
        if not metadata_path.is_file():
            raise CourseImportError("没有找到这份教材导入记录")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CourseImportError("教材导入记录已损坏") from exc
        if not isinstance(metadata, dict):
            raise CourseImportError("教材导入记录格式无效")
        return metadata

    @staticmethod
    def _chapter_snapshot(chapter: dict[str, Any]) -> dict[str, Any]:
        return {
            "chapter_index": int(chapter["chapter_index"]),
            "title": str(chapter["title"]),
            "start_page": int(chapter["start_page"]),
            "end_page": int(chapter["end_page"]),
        }

    @classmethod
    def _draft_is_stale(
        cls, record: dict[str, Any], chapter: dict[str, Any] | None
    ) -> bool:
        snapshot = record.get("chapter")
        if not isinstance(snapshot, dict) or chapter is None:
            return chapter is None
        return cls._chapter_snapshot(snapshot) != cls._chapter_snapshot(chapter)

    def create(self, data: bytes, *, filename: str) -> dict[str, Any]:
        import_id = hashlib.sha256(data).hexdigest()[:20]
        directory = self._directory(import_id)
        source_path = directory / "source.pdf"
        metadata_path = directory / "metadata.json"
        if source_path.is_file() and metadata_path.is_file():
            try:
                cached = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
            if cached.get("schema_version") == 2:
                return self.get(import_id)

        metadata = inspect_pdf_bytes(data, filename=filename)
        directory.mkdir(parents=True, exist_ok=True)
        if not source_path.is_file():
            temporary_source = directory / "source.pdf.tmp"
            temporary_source.write_bytes(data)
            temporary_source.replace(source_path)
        metadata = {
            **metadata,
            "schema_version": 2,
            "import_id": import_id,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "stored_locally": True,
        }
        self._write_json(metadata_path, metadata)
        return self.get(import_id)

    def _draft_summaries(
        self, import_id: str, chapters: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        directory = self._directory(import_id) / "drafts"
        if not directory.is_dir():
            return []
        chapter_map = {int(item["chapter_index"]): item for item in chapters}
        summaries: list[dict[str, Any]] = []
        for path in sorted(directory.glob("chapter-*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                blueprint = record.get("blueprint", {})
                chapter_index = int(record["chapter_index"])
                summaries.append(
                    {
                        "chapter_index": chapter_index,
                        "title": str(blueprint.get("course_title", "课程草稿")),
                        "lesson_count": len(blueprint.get("lessons", [])),
                        "saved_at": str(record["saved_at"]),
                        "stale": self._draft_is_stale(
                            record, chapter_map.get(chapter_index)
                        ),
                    }
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return summaries

    def _publication_summaries(self, import_id: str) -> list[dict[str, Any]]:
        directory = self._directory(import_id) / "published"
        if not directory.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(directory.glob("chapter-*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                blueprint = record.get("blueprint", {})
                summaries.append(
                    {
                        "chapter_index": int(record["chapter_index"]),
                        "lesson_id": str(record["lesson_id"]),
                        "title": str(blueprint.get("course_title", "已发布课程")),
                        "published_at": str(record["published_at"]),
                    }
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return summaries

    def get(self, import_id: str) -> dict[str, Any]:
        metadata = self._read_metadata(import_id)
        chapters = list(metadata.get("chapters", []))
        return {
            **metadata,
            "chapter_drafts": self._draft_summaries(import_id, chapters),
            "chapter_publications": self._publication_summaries(import_id),
        }

    def source_path(self, import_id: str) -> Path:
        path = self._directory(import_id) / "source.pdf"
        if not path.is_file():
            raise CourseImportError("没有找到这份教材的PDF源文件")
        return path

    def replace_chapters(
        self, import_id: str, chapters: list[dict[str, Any]]
    ) -> dict[str, Any]:
        metadata = self._read_metadata(import_id)
        existing = list(metadata.get("chapters", []))
        if len(chapters) != len(existing) or not chapters:
            raise CourseImportError("当前只支持调整已有内容单元，不能新增或删除")
        expected_indices = [int(item["chapter_index"]) for item in existing]
        received_indices = [int(item.get("chapter_index", -1)) for item in chapters]
        if received_indices != expected_indices:
            raise CourseImportError("内容单元顺序或编号已改变，请重新加载后再编辑")

        total_pages = int(metadata["total_pages"])
        normalized: list[dict[str, Any]] = []
        previous_end = 0
        for item in chapters:
            title = re.sub(r"\s+", " ", str(item.get("title", ""))).strip()
            if not title or len(title) > 100:
                raise CourseImportError("内容单元标题不能为空且不能超过100字")
            try:
                start_page = int(item["start_page"])
                end_page = int(item["end_page"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CourseImportError("内容单元页码无效") from exc
            if start_page < 1 or end_page > total_pages or end_page < start_page:
                raise CourseImportError(f"“{title}”的页码超出PDF范围")
            if start_page <= previous_end:
                raise CourseImportError("相邻内容单元不能重叠，且必须按页码递增")
            if end_page - start_page + 1 > MAX_STORED_CHAPTER_PAGES:
                raise CourseImportError(
                    f"“{title}”超过{MAX_STORED_CHAPTER_PAGES}页，请缩小范围"
                )
            normalized.append(
                {
                    "chapter_index": int(item["chapter_index"]),
                    "title": title,
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": end_page - start_page + 1,
                    "source": "manual",
                }
            )
            previous_end = end_page

        # Legacy drafts did not store their source range. Snapshot the old
        # chapter before applying edits so the UI can mark them stale safely.
        old_map = {int(item["chapter_index"]): item for item in existing}
        drafts_dir = self._directory(import_id) / "drafts"
        draft_paths = drafts_dir.glob("chapter-*.json") if drafts_dir.is_dir() else []
        for path in draft_paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                chapter_index = int(record["chapter_index"])
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(record.get("chapter"), dict) and chapter_index in old_map:
                record["chapter"] = self._chapter_snapshot(old_map[chapter_index])
                self._write_json(path, record)

        updated = {
            **metadata,
            "chapters": normalized,
            "chapter_detection": "manual",
            "structure_warning": "章节标题与页码已经人工调整。生成前仍建议预览正文。",
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._write_json(self._directory(import_id) / "metadata.json", updated)
        return self.get(import_id)

    def source_path(self, import_id: str) -> Path:
        path = self._directory(import_id) / "source.pdf"
        if not path.is_file():
            raise CourseImportError("教材PDF文件不存在")
        return path

    def preview_chapter(self, import_id: str, chapter_index: int) -> dict[str, Any]:
        metadata = self.get(import_id)
        chapter = next(
            (
                item
                for item in metadata.get("chapters", [])
                if int(item.get("chapter_index", -1)) == chapter_index
            ),
            None,
        )
        if chapter is None:
            raise CourseImportError("没有找到所选章节")
        result = preview_pdf_bytes(
            self.source_path(import_id).read_bytes(),
            filename=str(metadata.get("filename", "uploaded.pdf")),
            start_page=int(chapter["start_page"]),
            end_page=int(chapter["end_page"]),
            max_pages=MAX_STORED_CHAPTER_PAGES,
        )
        result["import_id"] = import_id
        result["chapter"] = chapter
        return result

    def save_chapter_blueprint(
        self,
        import_id: str,
        chapter_index: int,
        blueprint: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = self.get(import_id)
        chapter = next(
            (
                item
                for item in metadata.get("chapters", [])
                if int(item.get("chapter_index", -1)) == chapter_index
            ),
            None,
        )
        if chapter is None:
            raise CourseImportError("没有找到所选章节")
        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        record = {
            "import_id": import_id,
            "chapter_index": chapter_index,
            "saved_at": saved_at,
            "chapter": self._chapter_snapshot(chapter),
            "blueprint": blueprint,
        }
        drafts_dir = self._directory(import_id) / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        path = drafts_dir / f"chapter-{chapter_index:03d}.json"
        self._write_json(path, record)
        return {
            **blueprint,
            "draft": {
                "import_id": import_id,
                "chapter_index": chapter_index,
                "saved_at": saved_at,
                "stored_locally": True,
            },
        }

    def get_chapter_draft(self, import_id: str, chapter_index: int) -> dict[str, Any]:
        metadata = self.get(import_id)
        chapter = next(
            (
                item
                for item in metadata.get("chapters", [])
                if int(item.get("chapter_index", -1)) == chapter_index
            ),
            None,
        )
        path = self._directory(import_id) / "drafts" / f"chapter-{chapter_index:03d}.json"
        if not path.is_file():
            raise CourseImportError("这一章还没有课程草稿")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CourseImportError("章节课程草稿已损坏") from exc
        if self._draft_is_stale(record, chapter):
            raise CourseImportError("章节范围已经改变，请重新生成课程草稿后再发布")
        return record

    def get_chapter_blueprint(
        self, import_id: str, chapter_index: int
    ) -> dict[str, Any]:
        record = self.get_chapter_draft(import_id, chapter_index)
        blueprint = dict(record["blueprint"])
        return {
            **blueprint,
            "draft": {
                "import_id": import_id,
                "chapter_index": chapter_index,
                "saved_at": str(record["saved_at"]),
                "stored_locally": True,
            },
        }

    def publish_chapter_blueprint(
        self,
        import_id: str,
        chapter_index: int,
        *,
        lesson_id: str,
        blueprint: dict[str, Any],
    ) -> dict[str, Any]:
        draft = self.get_chapter_draft(import_id, chapter_index)
        published_at = datetime.now().astimezone().isoformat(timespec="seconds")
        record = {
            "lesson_id": lesson_id,
            "import_id": import_id,
            "chapter_index": chapter_index,
            "published_at": published_at,
            "source_draft_saved_at": str(draft["saved_at"]),
            "chapter": draft["chapter"],
            "blueprint": blueprint,
        }
        path = self._directory(import_id) / "published" / f"chapter-{chapter_index:03d}.json"
        self._write_json(path, record)
        return record

    def unpublish_chapter_blueprint(
        self, import_id: str, chapter_index: int
    ) -> dict[str, Any]:
        """Remove a published course while preserving its editable local draft."""
        self.get(import_id)
        path = self._directory(import_id) / "published" / f"chapter-{chapter_index:03d}.json"
        if not path.is_file():
            raise CourseImportError("这一章还没有已发布课程")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CourseImportError("已发布课程记录已损坏") from exc
        if not isinstance(record, dict) or not record.get("lesson_id"):
            raise CourseImportError("已发布课程记录格式无效")

        path.unlink()
        draft_path = (
            self._directory(import_id)
            / "drafts"
            / f"chapter-{chapter_index:03d}.json"
        )
        if draft_path.is_file():
            try:
                draft = json.loads(draft_path.read_text(encoding="utf-8"))
                blueprint = dict(draft.get("blueprint", {}))
                blueprint["status"] = "draft"
                grounding = dict(blueprint.get("grounding", {}))
                grounding["human_review_required"] = True
                blueprint["grounding"] = grounding
                draft["blueprint"] = blueprint
                self._write_json(draft_path, draft)
            except (OSError, TypeError, json.JSONDecodeError):
                # The publication is already removed. A damaged draft should not
                # make an otherwise successful unpublish operation look failed.
                pass
        return record

    def published_course_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*/published/chapter-*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(record, dict) and record.get("lesson_id"):
                    records.append(record)
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def published_course_record(self, lesson_id: str) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self.published_course_records()
                if str(record.get("lesson_id", "")) == lesson_id
            ),
            None,
        )

    def course_projects(self) -> list[dict[str, Any]]:
        """List every saved draft/publication across locally imported textbooks."""
        projects: list[dict[str, Any]] = []
        for directory in sorted(self.root.iterdir() if self.root.is_dir() else []):
            if not directory.is_dir() or not _IMPORT_ID_RE.fullmatch(directory.name):
                continue
            try:
                metadata = self._read_metadata(directory.name)
            except CourseImportError:
                continue
            chapter_map = {
                int(item["chapter_index"]): item
                for item in metadata.get("chapters", [])
                if isinstance(item, dict) and "chapter_index" in item
            }
            drafts = {
                int(item["chapter_index"]): item
                for item in self._draft_summaries(directory.name, list(chapter_map.values()))
            }
            publications = {
                int(item["chapter_index"]): item
                for item in self._publication_summaries(directory.name)
            }
            for chapter_index in sorted(set(drafts) | set(publications)):
                draft = drafts.get(chapter_index)
                publication = publications.get(chapter_index)
                chapter = chapter_map.get(chapter_index, {})
                projects.append(
                    {
                        "import_id": directory.name,
                        "filename": str(metadata.get("filename", "教材PDF")),
                        "chapter_index": chapter_index,
                        "chapter_title": str(chapter.get("title", f"第{chapter_index}部分")),
                        "course_title": str(
                            (publication or {}).get("title")
                            or (draft or {}).get("title")
                            or "未命名课程"
                        ),
                        "lesson_count": int((draft or {}).get("lesson_count", 0)),
                        "draft_saved_at": str((draft or {}).get("saved_at", "")),
                        "draft_stale": bool((draft or {}).get("stale", False)),
                        "published": publication is not None,
                        "lesson_id": str((publication or {}).get("lesson_id", "")),
                        "published_at": str((publication or {}).get("published_at", "")),
                    }
                )
        return sorted(
            projects,
            key=lambda item: item["published_at"] or item["draft_saved_at"],
            reverse=True,
        )

    def delete_course_project(
        self, import_id: str, chapter_index: int
    ) -> dict[str, Any]:
        """Delete one generated course draft and publication, retaining its source book."""
        self.get(import_id)
        directory = self._directory(import_id)
        published_path = directory / "published" / f"chapter-{chapter_index:03d}.json"
        draft_path = directory / "drafts" / f"chapter-{chapter_index:03d}.json"
        lesson_id = ""
        if published_path.is_file():
            try:
                published = json.loads(published_path.read_text(encoding="utf-8"))
                lesson_id = str(published.get("lesson_id", ""))
            except (OSError, json.JSONDecodeError):
                pass
        if not published_path.is_file() and not draft_path.is_file():
            raise CourseImportError("没有找到这门课程或课程草稿")
        published_removed = published_path.is_file()
        draft_removed = draft_path.is_file()
        published_path.unlink(missing_ok=True)
        draft_path.unlink(missing_ok=True)
        return {
            "lesson_id": lesson_id,
            "published_removed": published_removed,
            "draft_removed": draft_removed,
            "textbook_preserved": True,
        }
