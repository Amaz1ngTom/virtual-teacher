from __future__ import annotations

import re
import statistics
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader


MAX_PDF_BYTES = 150 * 1024 * 1024
MAX_PREVIEW_PAGES = 50
MIN_TEXT_LAYER_CHARS = 40
FALLBACK_WINDOW_PAGES = 30

_BOOKMARK_CHAPTER_RE = re.compile(
    r"^第\s*([0-9一二三四五六七八九十百]+)\s*章\s*(.+)$"
)
_ENGLISH_CHAPTER_RE = re.compile(
    r"^chapter\s+([0-9ivxlcdm]+)\s*[:.\-]?\s+(.{2,60})$", re.IGNORECASE
)
_PART_RE = re.compile(
    r"^第\s*([0-9一二三四五六七八九十百]+)\s*(部分|篇|单元)\s*(.{1,40})$"
)
_NUMBERED_MODULE_RE = re.compile(
    r"^(\d{1,3})\s*[.、:]\s*([^\d\s].{1,50})$"
)
_TERMINAL_HEADING_RE = re.compile(
    r"^(?:附录|后记|索引|参考文献|appendix|references|index)"
    r"(?:\s*[:：A-Z0-9一二三四五六七八九十].*)?$",
    re.IGNORECASE,
)

_CHAPTER_RE = re.compile(
    r"^第\s*([0-9一二三四五六七八九十百]+)\s*章\s*([^\n]{2,30})$"
)
_SECTION_RE = re.compile(
    r"^(\d{1,2}(?:\s*\.\s*\d{1,2}){1,2})\s*([^\n]{2,30})$"
)
_PAGE_NUMBER_RE = re.compile(r"^\s*[-—]?\s*\d{1,4}\s*[-—]?\s*$")


class CourseImportError(ValueError):
    pass


def _open_pdf(data: bytes) -> PdfReader:
    if len(data) < 8 or not data.startswith(b"%PDF"):
        raise CourseImportError("上传的文件不是有效PDF")
    if len(data) > MAX_PDF_BYTES:
        raise CourseImportError("PDF超过150MB，第一版暂不支持")
    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except Exception as exc:
        raise CourseImportError(f"PDF无法读取：{exc}") from exc
    if reader.is_encrypted:
        raise CourseImportError("第一版暂不支持加密PDF")
    if not reader.pages:
        raise CourseImportError("PDF没有可读取页面")
    return reader


def detect_bookmark_chapters(reader: PdfReader) -> list[dict[str, Any]]:
    """Return logical chapter ranges from top-level PDF bookmarks."""
    try:
        destinations = [
            item for item in reader.outline if not isinstance(item, list)
        ]
    except Exception:
        return []
    top_level_pages: list[int] = []
    chapter_starts: list[tuple[int, str, int]] = []
    for item in destinations:
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:
            continue
        if page_index < 0:
            continue
        top_level_pages.append(page_index)
        title = str(getattr(item, "title", "")).strip()
        match = _BOOKMARK_CHAPTER_RE.fullmatch(title)
        if match:
            chapter_starts.append((len(chapter_starts) + 1, title, page_index))

    chapters: list[dict[str, Any]] = []
    sorted_boundaries = sorted(set(top_level_pages))
    for chapter_index, title, start_index in chapter_starts:
        next_pages = [page for page in sorted_boundaries if page > start_index]
        end_index = next_pages[0] if next_pages else len(reader.pages)
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": title,
                "start_page": start_index + 1,
                "end_page": end_index,
                "page_count": end_index - start_index,
                "source": "pdf_bookmark",
            }
        )
    return chapters


def _valid_structure_title(title: str) -> bool:
    title = title.strip()
    return bool(title) and not re.search(r"[。；;，,？?！!]", title)


def _chapter_ranges(
    starts: list[tuple[str, int]],
    *,
    total_pages: int,
    source: str,
    terminal_pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    unique: list[tuple[str, int]] = []
    seen_titles: set[str] = set()
    for title, page_index in sorted(starts, key=lambda item: item[1]):
        normalized = re.sub(r"\s+", " ", title).strip()
        if normalized in seen_titles:
            continue
        unique.append((normalized, page_index))
        seen_titles.add(normalized)
    chapters: list[dict[str, Any]] = []
    terminals = sorted(set(terminal_pages or []))
    for index, (title, start_index) in enumerate(unique):
        later = [page for _next_title, page in unique[index + 1:] if page > start_index]
        later.extend(page for page in terminals if page > start_index)
        end_index = min(later) if later else total_pages
        if end_index <= start_index:
            continue
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": title,
                "start_page": start_index + 1,
                "end_page": end_index,
                "page_count": end_index - start_index,
                "source": source,
            }
        )
    return chapters


def detect_text_structure(reader: PdfReader) -> tuple[list[dict[str, Any]], int]:
    """Infer structure from visible heading lines when bookmarks are absent."""
    chapter_starts: list[tuple[str, int]] = []
    part_starts: list[tuple[str, int]] = []
    numbered_starts: list[tuple[str, int]] = []
    terminal_pages: list[int] = []
    text_layer_pages = 0
    for page_index, page in enumerate(reader.pages):
        text = extract_main_text(page)
        if len(text) >= MIN_TEXT_LAYER_CHARS:
            text_layer_pages += 1
        for raw_line in text.splitlines()[:14]:
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            if len(line) <= 40 and _TERMINAL_HEADING_RE.match(line):
                terminal_pages.append(page_index)
            chinese = _CHAPTER_RE.fullmatch(line)
            if chinese and _valid_structure_title(chinese.group(2)):
                chapter_starts.append(
                    (f"第{chinese.group(1)}章 {_normalize_title(chinese.group(2))}", page_index)
                )
                continue
            english = _ENGLISH_CHAPTER_RE.fullmatch(line)
            if english and _valid_structure_title(english.group(2)):
                chapter_starts.append(
                    (f"Chapter {english.group(1)} {_normalize_title(english.group(2))}", page_index)
                )
                continue
            part = _PART_RE.fullmatch(line)
            if part and _valid_structure_title(part.group(3)):
                part_starts.append(
                    (
                        f"第{part.group(1)}{part.group(2)} "
                        f"{_normalize_title(part.group(3))}",
                        page_index,
                    )
                )
                continue
            numbered = _NUMBERED_MODULE_RE.fullmatch(line)
            if numbered and _valid_structure_title(numbered.group(2)):
                numbered_starts.append(
                    (f"{numbered.group(1)}. {_normalize_title(numbered.group(2))}", page_index)
                )

    explicit_starts = chapter_starts or part_starts
    if explicit_starts:
        return (
            _chapter_ranges(
                explicit_starts,
                total_pages=len(reader.pages),
                source="text_heading",
                terminal_pages=terminal_pages,
            ),
            text_layer_pages,
        )
    distinct_numbers = {title.split(".", 1)[0] for title, _page in numbered_starts}
    if len(distinct_numbers) >= 2:
        return (
            _chapter_ranges(
                numbered_starts,
                total_pages=len(reader.pages),
                source="numbered_heading",
                terminal_pages=terminal_pages,
            ),
            text_layer_pages,
        )
    return [], text_layer_pages


def fixed_page_windows(total_pages: int) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for start_page in range(1, total_pages + 1, FALLBACK_WINDOW_PAGES):
        end_page = min(total_pages, start_page + FALLBACK_WINDOW_PAGES - 1)
        windows.append(
            {
                "chapter_index": len(windows) + 1,
                "title": f"内容单元{len(windows) + 1}",
                "start_page": start_page,
                "end_page": end_page,
                "page_count": end_page - start_page + 1,
                "source": "page_window",
            }
        )
    return windows


def inspect_pdf_bytes(data: bytes, *, filename: str) -> dict[str, Any]:
    """Inspect a full upload and build the best local chapter structure."""
    reader = _open_pdf(data)
    chapters = detect_bookmark_chapters(reader)
    text_layer_pages: int | None = None
    if not chapters:
        chapters, text_layer_pages = detect_text_structure(reader)
    if not chapters:
        chapters = fixed_page_windows(len(reader.pages))

    detection = str(chapters[0]["source"])
    warnings = {
        "pdf_bookmark": "已按PDF自带书签建立章节，仍建议抽查起止页。",
        "text_heading": "PDF没有章节书签，已根据正文中的章标题推断结构，请抽查起止页。",
        "numbered_heading": "PDF没有章节书签或明确章标题，已根据编号标题推断内容单元，请人工确认。",
        "page_window": (
            f"没有识别出可靠章节结构，已按每{FALLBACK_WINDOW_PAGES}页划分内容单元；"
            "生成课程前请人工确认范围。"
        ),
    }
    return {
        "filename": Path(filename).name or "uploaded.pdf",
        "file_size_bytes": len(data),
        "total_pages": len(reader.pages),
        "chapter_detection": detection,
        "structure_warning": warnings[detection],
        "chapters": chapters,
        "ocr_used": False,
        "requires_ocr": text_layer_pages == 0 if text_layer_pages is not None else False,
        "scanned_text_layer_pages": text_layer_pages,
    }


def _normalize_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .。·-—")
    return value[:80]


def clean_page_text(raw_text: str) -> str:
    """Conservative cleanup that keeps headings and source wording intact."""
    raw_text = raw_text.replace("\u00a0", " ").replace("\u3000", " ")
    raw_text = raw_text.replace("\x00", "")
    lines: list[str] = []
    for raw_line in raw_text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line or _PAGE_NUMBER_RE.fullmatch(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _join_fragments(fragments: list[str]) -> str:
    output = ""
    for fragment in fragments:
        if not fragment:
            continue
        if (
            output
            and output[-1].isascii()
            and output[-1].isalnum()
            and fragment[0].isascii()
            and fragment[0].isalnum()
        ):
            output += " "
        output += fragment
    return output.strip()


def extract_main_text(page: Any) -> str:
    """Extract reading-order text while suppressing narrow margin notes.

    The dominant left edge is estimated from long text fragments, so ordinary
    single-column PDFs keep their original margin while textbook side notes
    are excluded without hard-coding this book's page size.
    """
    fragments: list[tuple[float, float, str]] = []

    def visitor(text, _cm, tm, _font, _font_size):
        normalized = " ".join(str(text).split())
        if normalized:
            fragments.append((float(tm[4]), float(tm[5]), normalized))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return clean_page_text(page.extract_text() or "")
    if not fragments:
        return ""

    long_fragment_x = [x for x, _y, text in fragments if len(text) >= 18]
    if long_fragment_x:
        dominant_left = statistics.median(long_fragment_x)
    else:
        dominant_left = min(x for x, _y, _text in fragments)
    left_cutoff = max(0.0, dominant_left - 28.0)
    page_height = float(page.mediabox.height)
    bottom_cutoff = page_height * 0.035
    top_cutoff = page_height * 0.97

    rows: list[dict[str, Any]] = []
    for x, y, text in sorted(fragments, key=lambda item: (-item[1], item[0])):
        if x < left_cutoff or y < bottom_cutoff or y > top_cutoff:
            continue
        target = next((row for row in rows if abs(row["y"] - y) <= 2.2), None)
        if target is None:
            target = {"y": y, "items": []}
            rows.append(target)
        target["items"].append((x, text))

    lines = []
    for row in sorted(rows, key=lambda item: -item["y"]):
        pieces = [text for _x, text in sorted(row["items"], key=lambda item: item[0])]
        line = _join_fragments(pieces)
        if line:
            lines.append(line)
    return clean_page_text("\n".join(lines))


def detect_headings(text: str, page_number: int) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        chapter_match = _CHAPTER_RE.fullmatch(line)
        if chapter_match:
            title_part = _normalize_title(chapter_match.group(2))
            if not re.search(r"[。；;，,：:？?（）()]", title_part):
                title = _normalize_title(
                    f"第{chapter_match.group(1)}章 {title_part}"
                )
                key = (1, title)
                if title and key not in seen:
                    headings.append(
                        {"level": 1, "title": title, "page_number": page_number}
                    )
                    seen.add(key)
            continue

        # Running headers may append the printed page number, for example
        # "2.2 评估方法 25". Normalize it before deduplication.
        line = re.sub(r"(?<=\D)\s+\d{1,4}$", "", line)
        section_match = _SECTION_RE.fullmatch(line)
        if not section_match:
            continue
        title_part = _normalize_title(section_match.group(2))
        if re.search(r"[。；;，,：:？?（）()]", title_part):
            continue
        if any(marker in title_part for marker in ("参见", "见图", "示意图")):
            continue
        number = re.sub(r"\s+", "", section_match.group(1))
        title = _normalize_title(f"{number} {title_part}")
        level = min(3, number.count(".") + 1)
        key = (level, title)
        if title and key not in seen:
            headings.append(
                {"level": level, "title": title, "page_number": page_number}
            )
            seen.add(key)
    return headings


def preview_pdf_bytes(
    data: bytes,
    *,
    filename: str,
    start_page: int,
    end_page: int,
    max_pages: int = MAX_PREVIEW_PAGES,
) -> dict[str, Any]:
    reader = _open_pdf(data)

    total_pages = len(reader.pages)
    if start_page < 1 or end_page < start_page or end_page > total_pages:
        raise CourseImportError(f"页码范围必须在1到{total_pages}之间")
    if end_page - start_page + 1 > max_pages:
        raise CourseImportError(f"一次最多处理{max_pages}页")

    pages: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    seen_sections: set[tuple[int, str]] = set()
    text_layer_pages = 0
    skipped_pages: list[int] = []
    for page_number in range(start_page, end_page + 1):
        page = reader.pages[page_number - 1]
        try:
            text = extract_main_text(page)
        except Exception:
            text = ""
        has_text_layer = len(text) >= MIN_TEXT_LAYER_CHARS
        headings = detect_headings(text, page_number) if has_text_layer else []
        if has_text_layer:
            text_layer_pages += 1
            for heading in headings:
                key = (int(heading["level"]), str(heading["title"]))
                if key not in seen_sections:
                    sections.append(heading)
                    seen_sections.add(key)
        else:
            skipped_pages.append(page_number)
        pages.append(
            {
                "page_number": page_number,
                "character_count": len(text),
                "has_text_layer": has_text_layer,
                "headings": headings,
                "text": text if has_text_layer else "",
            }
        )

    return {
        "filename": Path(filename).name or "uploaded.pdf",
        "file_size_bytes": len(data),
        "total_pages": total_pages,
        "start_page": start_page,
        "end_page": end_page,
        "preview_page_count": len(pages),
        "text_layer_pages": text_layer_pages,
        "skipped_pages": skipped_pages,
        "ocr_used": False,
        "sections": sections,
        "pages": pages,
    }
