from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter


CHAPTER_RE = re.compile(r"^第\s*(\d+)\s*章\s*(.+)$")


def top_level_destinations(reader: PdfReader) -> list[Any]:
    return [item for item in reader.outline if not isinstance(item, list)]


def safe_title(title: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "-", title).strip().rstrip(".")


def split_chapters(input_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    reader = PdfReader(input_path, strict=False)
    if reader.is_encrypted:
        raise ValueError("暂不支持加密PDF")
    destinations = top_level_destinations(reader)
    chapter_positions: list[tuple[int, str, int]] = []
    for item in destinations:
        title = str(item.title).strip()
        match = CHAPTER_RE.fullmatch(title)
        if not match:
            continue
        chapter_positions.append(
            (int(match.group(1)), title, reader.get_destination_page_number(item))
        )
    if not chapter_positions:
        raise ValueError("PDF顶层书签中没有识别到“第N章”")

    all_top_level_pages = sorted(
        {
            reader.get_destination_page_number(item)
            for item in destinations
            if reader.get_destination_page_number(item) >= 0
        }
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, Any]] = []
    for chapter_number, title, start_index in chapter_positions:
        next_pages = [page for page in all_top_level_pages if page > start_index]
        end_index = next_pages[0] if next_pages else len(reader.pages)
        output_path = output_dir / (
            f"{chapter_number:02d}-{safe_title(title)}.pdf"
        )
        writer = PdfWriter()
        for page_index in range(start_index, end_index):
            writer.add_page(reader.pages[page_index])
        writer.add_metadata(
            {
                "/Title": title,
                "/Subject": f"从{input_path.name}按顶层书签拆分",
            }
        )
        if end_index > start_index:
            writer.add_outline_item(title, 0)
        with output_path.open("wb") as handle:
            writer.write(handle)
        manifest.append(
            {
                "chapter_number": chapter_number,
                "title": title,
                "source_pdf_start_page": start_index + 1,
                "source_pdf_end_page": end_index,
                "page_count": end_index - start_index,
                "filename": output_path.name,
                "size_bytes": output_path.stat().st_size,
            }
        )

    (output_dir / "chapters.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="按PDF顶层章节书签拆分教材")
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    manifest = split_chapters(args.input.resolve(), args.output_dir.resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
