from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.conversation_store import SQLiteConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_free_chat_can_be_listed_restored_and_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteConversationStore(Path(directory) / "conversations.sqlite3")
            try:
                store.record_turn(
                    user_id="student",
                    thread_id="thread-a",
                    user_text="给我讲讲高等数学中的极限",
                    assistant_text="我们从极限的直观概念开始。",
                    emotion="neutral",
                    teaching_state=None,
                )
                store.record_turn(
                    user_id="student",
                    thread_id="thread-a",
                    user_text="继续",
                    assistant_text="接下来介绍数列极限。",
                    emotion="happy",
                    teaching_state={"lesson_mode": "dynamic"},
                )

                sessions = store.list_sessions("student")
                self.assertEqual(len(sessions), 1)
                self.assertEqual(sessions[0]["thread_id"], "thread-a")
                self.assertEqual(sessions[0]["message_count"], 4)

                restored = store.get_session("student", "thread-a")
                self.assertIsNotNone(restored)
                self.assertEqual(restored["title"], "给我讲讲高等数学中的极限")
                self.assertEqual(
                    [message["role"] for message in restored["messages"]],
                    ["user", "assistant", "user", "assistant"],
                )
                self.assertEqual(
                    restored["teaching_state"], {"lesson_mode": "dynamic"}
                )

                self.assertTrue(store.delete_session("student", "thread-a"))
                self.assertEqual(store.list_sessions("student"), [])
            finally:
                store.close()

    def test_sessions_are_isolated_by_user(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteConversationStore(Path(directory) / "conversations.sqlite3")
            try:
                store.record_turn(
                    user_id="student-a",
                    thread_id="thread-a",
                    user_text="问题A",
                    assistant_text="回答A",
                    emotion=None,
                    teaching_state=None,
                )
                self.assertEqual(len(store.list_sessions("student-a")), 1)
                self.assertEqual(store.list_sessions("student-b"), [])
                self.assertIsNone(store.get_session("student-b", "thread-a"))
                self.assertFalse(store.delete_session("student-b", "thread-a"))
            finally:
                store.close()

    def test_new_temporary_course_replaces_previous_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteConversationStore(Path(directory) / "conversations.sqlite3")
            try:
                first = store.replace_temporary_thread(
                    user_id="student",
                    lesson_id="python-lecture",
                    thread_id="temporary-1",
                )
                second = store.replace_temporary_thread(
                    user_id="student",
                    lesson_id="python-lecture",
                    thread_id="temporary-2",
                )
                same = store.replace_temporary_thread(
                    user_id="student",
                    lesson_id="python-lecture",
                    thread_id="temporary-2",
                )
                self.assertIsNone(first)
                self.assertEqual(second, "temporary-1")
                self.assertIsNone(same)
                self.assertTrue(
                    store.delete_temporary_thread("student", "temporary-2")
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
