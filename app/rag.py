from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pypdf import PdfReader

from app.course_import import CourseImportError, extract_main_text
from app.embeddings import LocalBGEEmbedder


RAG_BACKEND = "local-char-bm25-v1"
HYBRID_RAG_BACKEND = "local-bm25-bge-hybrid-v1"
TARGET_CHUNK_CHARS = 520
MAX_CHUNK_CHARS = 760
CHUNK_OVERLAP_CHARS = 80
MAX_QUERY_TOKENS = 80

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)
_HAN_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")


def retrieval_tokens(text: str) -> list[str]:
    """Tokenize Chinese without external dictionaries or model weights."""
    normalized = text.lower()
    tokens = [f"en:{token}" for token in _ASCII_TOKEN_RE.findall(normalized)]
    for run in _HAN_RUN_RE.findall(normalized):
        compact = re.sub(r"\s+", "", run)
        if len(compact) == 1:
            tokens.append(f"zh1:{compact}")
            continue
        for size in (2, 3):
            if len(compact) < size:
                continue
            tokens.extend(
                f"zh{size}:{compact[index:index + size]}"
                for index in range(len(compact) - size + 1)
            )
    return tokens


def chunk_page_text(text: str) -> list[str]:
    """Build readable, page-bounded chunks with light sentence overlap."""
    cleaned = re.sub(r"[ \t]+", " ", text).strip()
    if not cleaned:
        return []
    sentences: list[str] = []
    for paragraph in cleaned.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= MAX_CHUNK_CHARS:
                sentences.append(sentence)
                continue
            start = 0
            while start < len(sentence):
                end = min(len(sentence), start + MAX_CHUNK_CHARS)
                sentences.append(sentence[start:end])
                if end >= len(sentence):
                    break
                start = max(start + 1, end - CHUNK_OVERLAP_CHARS)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current}\n{sentence}".strip() if current else sentence
        if current and len(candidate) > TARGET_CHUNK_CHARS:
            chunks.append(current)
            overlap = current[-CHUNK_OVERLAP_CHARS:].lstrip()
            candidate = f"{overlap}\n{sentence}".strip() if overlap else sentence
        current = candidate
    if current:
        chunks.append(current)
    return chunks


class TextbookRAGStore:
    """Persistent BM25 index with optional local semantic-vector fusion."""

    def __init__(self, path: Path, *, embedder: LocalBGEEmbedder | None = None):
        self.path = path.resolve()
        self.embedder = embedder
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    import_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    total_pages INTEGER NOT NULL,
                    text_pages INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    average_chunk_tokens REAL NOT NULL,
                    backend TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    import_id TEXT NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    chapter_index INTEGER,
                    chapter_title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    PRIMARY KEY (import_id, chunk_id)
                );
                CREATE TABLE IF NOT EXISTS postings (
                    import_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    term_frequency INTEGER NOT NULL,
                    PRIMARY KEY (import_id, token, chunk_id)
                );
                CREATE INDEX IF NOT EXISTS idx_postings_lookup
                    ON postings(import_id, token);
                CREATE TABLE IF NOT EXISTS token_stats (
                    import_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    document_frequency INTEGER NOT NULL,
                    PRIMARY KEY (import_id, token)
                );
                CREATE TABLE IF NOT EXISTS embeddings (
                    import_id TEXT NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (import_id, chunk_id)
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(documents)")
            }
            for name, declaration in (
                ("embedding_model", "TEXT"),
                ("embedding_dimension", "INTEGER"),
                ("embedding_error", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE documents ADD COLUMN {name} {declaration}"
                    )

    @staticmethod
    def _chapter_for_page(
        chapters: list[dict[str, Any]], page_number: int
    ) -> dict[str, Any] | None:
        return next(
            (
                chapter
                for chapter in chapters
                if int(chapter["start_page"]) <= page_number <= int(chapter["end_page"])
            ),
            None,
        )

    def index_pdf(
        self,
        *,
        import_id: str,
        source_path: Path,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            reader = PdfReader(str(source_path), strict=False)
        except Exception as exc:
            raise CourseImportError(f"教材PDF无法建立检索索引：{exc}") from exc
        chapters = list(metadata.get("chapters", []))
        chunk_rows: list[tuple[Any, ...]] = []
        posting_rows: list[tuple[Any, ...]] = []
        document_frequencies: Counter[str] = Counter()
        text_pages = 0
        total_tokens = 0
        chunk_id = 0

        for page_index, page in enumerate(reader.pages):
            page_number = page_index + 1
            text = extract_main_text(page)
            page_chunks = chunk_page_text(text)
            if page_chunks:
                text_pages += 1
            chapter = self._chapter_for_page(chapters, page_number)
            for chunk in page_chunks:
                counts = Counter(retrieval_tokens(chunk))
                if not counts:
                    continue
                chunk_id += 1
                token_count = sum(counts.values())
                total_tokens += token_count
                chapter_index = int(chapter["chapter_index"]) if chapter else None
                chapter_title = str(chapter["title"]) if chapter else "未归类页面"
                chunk_rows.append(
                    (
                        import_id,
                        chunk_id,
                        page_number,
                        chapter_index,
                        chapter_title,
                        chunk,
                        token_count,
                    )
                )
                document_frequencies.update(counts.keys())
                posting_rows.extend(
                    (import_id, token, chunk_id, frequency)
                    for token, frequency in counts.items()
                )

        if not chunk_rows:
            raise CourseImportError("教材没有可建立RAG索引的文字层，请先完成OCR")

        embedding_rows: list[tuple[Any, ...]] = []
        embedding_model: str | None = None
        embedding_dimension: int | None = None
        embedding_error = ""
        if self.embedder is not None and self.embedder.available:
            try:
                vectors = self.embedder.encode((row[5] for row in chunk_rows))
                if len(vectors) != len(chunk_rows):
                    raise RuntimeError("Embedding数量与教材片段数量不一致")
                embedding_dimension = int(vectors.shape[1])
                embedding_model = self.embedder.model_name
                embedding_rows = [
                    (
                        import_id,
                        int(chunk_rows[index][1]),
                        embedding_dimension,
                        vector.astype(np.float32, copy=False).tobytes(),
                    )
                    for index, vector in enumerate(vectors)
                ]
            except Exception as exc:
                embedding_error = str(exc)[:500]

        indexed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        average_tokens = total_tokens / len(chunk_rows)
        backend = HYBRID_RAG_BACKEND if embedding_rows else RAG_BACKEND
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table in (
                "postings", "token_stats", "embeddings", "chunks", "documents"
            ):
                connection.execute(f"DELETE FROM {table} WHERE import_id = ?", (import_id,))
            connection.executemany(
                """INSERT INTO chunks(
                    import_id, chunk_id, page_number, chapter_index,
                    chapter_title, text, token_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                chunk_rows,
            )
            connection.executemany(
                "INSERT INTO postings(import_id, token, chunk_id, term_frequency) VALUES (?, ?, ?, ?)",
                posting_rows,
            )
            connection.executemany(
                "INSERT INTO token_stats(import_id, token, document_frequency) VALUES (?, ?, ?)",
                (
                    (import_id, token, frequency)
                    for token, frequency in document_frequencies.items()
                ),
            )
            if embedding_rows:
                connection.executemany(
                    "INSERT INTO embeddings(import_id, chunk_id, dimension, vector) VALUES (?, ?, ?, ?)",
                    embedding_rows,
                )
            connection.execute(
                """INSERT INTO documents(
                    import_id, filename, total_pages, text_pages, chunk_count,
                    average_chunk_tokens, backend, indexed_at, embedding_model,
                    embedding_dimension, embedding_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    str(metadata.get("filename", source_path.name)),
                    len(reader.pages),
                    text_pages,
                    len(chunk_rows),
                    average_tokens,
                    backend,
                    indexed_at,
                    embedding_model,
                    embedding_dimension,
                    embedding_error,
                ),
            )
            connection.commit()
        return self.status(import_id)

    def status(self, import_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE import_id = ?", (import_id,)
            ).fetchone()
        if row is None:
            return {
                "import_id": import_id,
                "indexed": False,
                "backend": RAG_BACKEND,
                "embedding_model": (
                    self.embedder.model_name
                    if self.embedder is not None and self.embedder.available
                    else None
                ),
                "embedding_configured": bool(
                    self.embedder is not None and self.embedder.available
                ),
                "semantic_indexed": False,
            }
        return {
            **dict(row),
            "indexed": True,
            "embedding_configured": bool(
                self.embedder is not None and self.embedder.available
            ),
            "semantic_indexed": bool(
                row["embedding_model"]
                and self.embedder is not None
                and self.embedder.available
                and row["embedding_model"] == self.embedder.model_name
            ),
            "embedding_stale": bool(
                row["embedding_model"]
                and self.embedder is not None
                and self.embedder.available
                and row["embedding_model"] != self.embedder.model_name
            ),
        }

    @staticmethod
    def _keyword_scores(
        connection: sqlite3.Connection,
        import_id: str,
        query: str,
        document: sqlite3.Row,
    ) -> dict[int, float]:
        query_counts = Counter(retrieval_tokens(query))
        if not query_counts:
            return {}
        query_tokens = list(query_counts)[:MAX_QUERY_TOKENS]
        placeholders = ",".join("?" for _ in query_tokens)
        stats = {
            str(row["token"]): int(row["document_frequency"])
            for row in connection.execute(
                f"""SELECT token, document_frequency FROM token_stats
                WHERE import_id = ? AND token IN ({placeholders})""",
                (import_id, *query_tokens),
            )
        }
        posting_rows = connection.execute(
            f"""SELECT token, chunk_id, term_frequency FROM postings
            WHERE import_id = ? AND token IN ({placeholders})""",
            (import_id, *query_tokens),
        ).fetchall()
        if not posting_rows:
            return {}
        chunk_ids = sorted({int(row["chunk_id"]) for row in posting_rows})
        chunk_placeholders = ",".join("?" for _ in chunk_ids)
        lengths = {
            int(row["chunk_id"]): int(row["token_count"])
            for row in connection.execute(
                f"""SELECT chunk_id, token_count FROM chunks WHERE import_id = ?
                AND chunk_id IN ({chunk_placeholders})""",
                (import_id, *chunk_ids),
            )
        }
        total_documents = int(document["chunk_count"])
        average_length = max(1.0, float(document["average_chunk_tokens"]))
        scores: Counter[int] = Counter()
        k1 = 1.5
        b = 0.75
        for row in posting_rows:
            token = str(row["token"])
            chunk_id = int(row["chunk_id"])
            frequency = int(row["term_frequency"])
            document_frequency = max(1, stats.get(token, 1))
            inverse_frequency = math.log(
                1 + (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            length = lengths.get(chunk_id, 1)
            denominator = frequency + k1 * (1 - b + b * length / average_length)
            scores[chunk_id] += (
                inverse_frequency
                * frequency
                * (k1 + 1)
                / denominator
                * min(2, query_counts[token])
            )
        return dict(scores)

    def _semantic_scores(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        query: str,
        document: sqlite3.Row,
    ) -> dict[int, float]:
        if (
            self.embedder is None
            or not self.embedder.available
            or not document["embedding_model"]
            or document["embedding_model"] != self.embedder.model_name
        ):
            return {}
        query_vector = self.embedder.encode([query], is_query=True)[0]
        scores: dict[int, float] = {}
        for row in connection.execute(
            "SELECT chunk_id, dimension, vector FROM embeddings WHERE import_id = ?",
            (import_id,),
        ):
            if int(row["dimension"]) != len(query_vector):
                continue
            vector = np.frombuffer(row["vector"], dtype=np.float32)
            scores[int(row["chunk_id"])] = float(vector @ query_vector)
        return scores

    def search(
        self, import_id: str, query: str, *, top_k: int = 4
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            document = connection.execute(
                "SELECT * FROM documents WHERE import_id = ?",
                (import_id,),
            ).fetchone()
            if document is None:
                return []
            keyword_scores = self._keyword_scores(
                connection, import_id, query, document
            )
            try:
                semantic_scores = self._semantic_scores(
                    connection, import_id, query, document
                )
            except Exception:
                semantic_scores = {}
            keyword_ranked = sorted(
                keyword_scores, key=keyword_scores.get, reverse=True
            )[:100]
            semantic_ranked = sorted(
                semantic_scores, key=semantic_scores.get, reverse=True
            )[:100]
            fused: Counter[int] = Counter()
            for rank, chunk_id in enumerate(keyword_ranked, start=1):
                fused[chunk_id] += 0.45 / (60 + rank)
            for rank, chunk_id in enumerate(semantic_ranked, start=1):
                fused[chunk_id] += 0.55 / (60 + rank)
            candidate_ids = [
                chunk_id
                for chunk_id, _ in fused.most_common(50)
            ]
            if not candidate_ids:
                return []
            chunk_placeholders = ",".join("?" for _ in candidate_ids)
            chunks = {
                int(row["chunk_id"]): row
                for row in connection.execute(
                    f"""SELECT * FROM chunks WHERE import_id = ?
                    AND chunk_id IN ({chunk_placeholders})""",
                    (import_id, *candidate_ids),
                )
            }
            limit = max(1, min(10, top_k))
            selected: list[int] = []
            seen_pages: set[int] = set()
            for chunk_id in candidate_ids:
                page_number = int(chunks[chunk_id]["page_number"])
                if page_number in seen_pages:
                    continue
                selected.append(chunk_id)
                seen_pages.add(page_number)
                if len(selected) >= limit:
                    break
            if len(selected) < limit:
                selected.extend(
                    chunk_id
                    for chunk_id in candidate_ids
                    if chunk_id not in selected
                )
                selected = selected[:limit]

        results: list[dict[str, Any]] = []
        backend = HYBRID_RAG_BACKEND if semantic_scores else RAG_BACKEND
        for chunk_id in selected:
            row = chunks[chunk_id]
            results.append(
                {
                    "chunk_id": chunk_id,
                    "page_number": int(row["page_number"]),
                    "chapter_index": row["chapter_index"],
                    "chapter_title": str(row["chapter_title"]),
                    "text": str(row["text"]),
                    "score": round(float(fused[chunk_id] * 1000), 4),
                    "lexical_score": round(float(keyword_scores.get(chunk_id, 0.0)), 4),
                    "semantic_score": round(float(semantic_scores.get(chunk_id, 0.0)), 4),
                    "backend": backend,
                }
            )
        return results


def format_retrieval_context(results: list[dict[str, Any]]) -> str:
    blocks = []
    for result in results:
        blocks.append(
            f"[PDF第{result['page_number']}页｜{result['chapter_title']}]\n"
            f"{result['text']}"
        )
    return "\n\n".join(blocks)
