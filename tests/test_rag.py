from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from app.rag import TextbookRAGStore, chunk_page_text, retrieval_tokens
from tests.test_course_import import _pages_pdf


class TextbookRAGTests(unittest.TestCase):
    def test_chinese_tokenization_needs_no_external_model(self):
        tokens = retrieval_tokens("机器学习中的泛化能力")

        self.assertIn("zh2:机器", tokens)
        self.assertIn("zh3:机器学", tokens)
        self.assertNotEqual(tokens, [])

    def test_long_text_is_split_into_bounded_overlapping_chunks(self):
        chunks = chunk_page_text("第一句用于说明。" * 120)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 840 for chunk in chunks))

    def test_index_and_search_return_pdf_page_and_chapter(self):
        pages = _pages_pdf(
            [
                ["Chapter One", "Linear regression estimates continuous values."],
                ["Chapter Two", "Overfitting hurts generalization on unseen test data."],
            ]
        )
        metadata = {
            "filename": "machine-learning.pdf",
            "chapters": [
                {"chapter_index": 1, "title": "Regression", "start_page": 1, "end_page": 1},
                {"chapter_index": 2, "title": "Generalization", "start_page": 2, "end_page": 2},
            ],
        }

        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(pages)
            store = TextbookRAGStore(Path(directory) / "rag.sqlite3")
            status = store.index_pdf(
                import_id="abc123",
                source_path=source,
                metadata=metadata,
            )
            results = store.search("abc123", "Why does overfitting hurt generalization?")

        self.assertTrue(status["indexed"])
        self.assertEqual(status["text_pages"], 2)
        self.assertGreaterEqual(status["chunk_count"], 2)
        self.assertEqual(results[0]["page_number"], 2)
        self.assertEqual(results[0]["chapter_title"], "Generalization")

    def test_hybrid_index_uses_semantics_when_query_has_no_keyword_overlap(self):
        class FakeEmbedder:
            available = True
            model_name = "fake-bge"

            @staticmethod
            def encode(texts, *, is_query=False):
                vectors = []
                for text in list(texts):
                    lowered = text.lower()
                    if "automobile" in lowered or "car" in lowered:
                        vectors.append([1.0, 0.0])
                    else:
                        vectors.append([0.0, 1.0])
                return np.asarray(vectors, dtype=np.float32)

        pages = _pages_pdf([
            ["A car transports people on roads."],
            ["A banana is a yellow fruit."],
        ])
        metadata = {
            "filename": "semantic.pdf",
            "chapters": [{
                "chapter_index": 1,
                "title": "Objects",
                "start_page": 1,
                "end_page": 2,
            }],
        }
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(pages)
            store = TextbookRAGStore(
                Path(directory) / "rag.sqlite3", embedder=FakeEmbedder()
            )
            status = store.index_pdf(
                import_id="semantic",
                source_path=source,
                metadata=metadata,
            )
            results = store.search("semantic", "automobile", top_k=1)

        self.assertTrue(status["semantic_indexed"])
        self.assertEqual(status["embedding_model"], "fake-bge")
        self.assertEqual(results[0]["page_number"], 1)
        self.assertEqual(results[0]["backend"], "local-bm25-bge-hybrid-v1")


if __name__ == "__main__":
    unittest.main()
