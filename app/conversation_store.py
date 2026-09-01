from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _title_from_text(text: str, *, max_length: int = 24) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return "新的学习问答"
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}…"


class SQLiteConversationStore:
    """UI-facing free-chat history, separate from LangGraph checkpoints."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    lesson_id TEXT NOT NULL DEFAULT 'default',
                    teaching_state_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_sessions_user_updated
                ON conversation_sessions(user_id, updated_at DESC)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    text TEXT NOT NULL,
                    emotion TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES conversation_sessions(thread_id)
                        ON DELETE CASCADE
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_id
                ON conversation_messages(thread_id, id)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS temporary_threads (
                    user_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL UNIQUE,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, lesson_id)
                )
                """
            )

    def record_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        user_text: str | None,
        assistant_text: str,
        emotion: str | None,
        teaching_state: dict[str, Any] | None,
    ) -> None:
        timestamp = _utc_now()
        title_source = user_text or assistant_text
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO conversation_sessions(
                    thread_id, user_id, title, lesson_id,
                    teaching_state_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'default', ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    teaching_state_json = excluded.teaching_state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    thread_id,
                    user_id,
                    _title_from_text(title_source),
                    json.dumps(teaching_state, ensure_ascii=False)
                    if teaching_state is not None
                    else None,
                    timestamp,
                    timestamp,
                ),
            )
            if user_text:
                self._connection.execute(
                    """
                    INSERT INTO conversation_messages(
                        thread_id, role, text, emotion, created_at
                    ) VALUES (?, 'user', ?, NULL, ?)
                    """,
                    (thread_id, user_text, timestamp),
                )
            self._connection.execute(
                """
                INSERT INTO conversation_messages(
                    thread_id, role, text, emotion, created_at
                ) VALUES (?, 'assistant', ?, ?, ?)
                """,
                (thread_id, assistant_text, emotion, timestamp),
            )

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT s.thread_id, s.title, s.created_at, s.updated_at,
                       COUNT(m.id) AS message_count
                FROM conversation_sessions AS s
                LEFT JOIN conversation_messages AS m ON m.thread_id = s.thread_id
                WHERE s.user_id = ? AND s.lesson_id = 'default'
                GROUP BY s.thread_id
                ORDER BY s.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, user_id: str, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._connection.execute(
                """
                SELECT thread_id, title, lesson_id, teaching_state_json,
                       created_at, updated_at
                FROM conversation_sessions
                WHERE user_id = ? AND thread_id = ?
                """,
                (user_id, thread_id),
            ).fetchone()
            if session is None:
                return None
            messages = self._connection.execute(
                """
                SELECT id, role, text, emotion, created_at
                FROM conversation_messages
                WHERE thread_id = ?
                ORDER BY id
                """,
                (thread_id,),
            ).fetchall()
        payload = dict(session)
        raw_state = payload.pop("teaching_state_json")
        payload["teaching_state"] = json.loads(raw_state) if raw_state else None
        payload["messages"] = [dict(row) for row in messages]
        return payload

    def delete_session(self, user_id: str, thread_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM conversation_sessions WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            )
            self._connection.execute(
                "DELETE FROM temporary_threads WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            )
        return cursor.rowcount > 0

    def replace_temporary_thread(
        self, *, user_id: str, lesson_id: str, thread_id: str
    ) -> str | None:
        timestamp = _utc_now()
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT thread_id FROM temporary_threads
                WHERE user_id = ? AND lesson_id = ?
                """,
                (user_id, lesson_id),
            ).fetchone()
            old_thread_id = str(row[0]) if row else None
            self._connection.execute(
                """
                INSERT INTO temporary_threads(user_id, lesson_id, thread_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    updated_at = excluded.updated_at
                """,
                (user_id, lesson_id, thread_id, timestamp),
            )
        return old_thread_id if old_thread_id != thread_id else None

    def delete_temporary_thread(self, user_id: str, thread_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM temporary_threads WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            )
        return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()
