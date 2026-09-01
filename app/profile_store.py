from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SQLiteProfileStore:
    """Small persistent store for cross-thread user memory.

    LangGraph owns the load/save workflow. SQLite makes the local MVP survive
    process restarts. A production deployment can replace this with
    PostgresStore without changing the graph's teaching logic.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def merge(self, user_id: str, update: dict[str, Any]) -> dict[str, Any]:
        if not update:
            return self.get(user_id)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            profile = json.loads(row[0]) if row else {}
            profile.update(update)
            self._conn.execute(
                """
                INSERT INTO user_profiles(user_id, profile_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, json.dumps(profile, ensure_ascii=False)),
            )
        return profile

    def close(self) -> None:
        with self._lock:
            self._conn.close()

