"""Unit tests for the SQLite message store."""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chat.store import MIGRATIONS, Store, dm_key


class StoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")

    async def asyncTearDown(self):
        await self.store.close()

    async def test_room_messages_get_increasing_ids_and_round_trip(self):
        first = await self.store.add_room_message("lobby", "alice", "one")
        second = await self.store.add_room_message("lobby", "bob", "two")
        self.assertLess(first["id"], second["id"])
        self.assertEqual(first["room"], "lobby")
        self.assertEqual(first["username"], "alice")
        self.assertEqual(first["text"], "one")
        self.assertIn("T", first["time"])

        messages, has_more = await self.store.room_history("lobby")
        self.assertEqual([m["text"] for m in messages], ["one", "two"])
        self.assertFalse(has_more)
        self.assertEqual(messages[0], first)

    async def test_history_is_scoped_to_one_room(self):
        await self.store.add_room_message("lobby", "alice", "in lobby")
        await self.store.add_room_message("study", "alice", "in study")
        messages, _ = await self.store.room_history("study")
        self.assertEqual([m["text"] for m in messages], ["in study"])

    async def test_history_pages_backwards_oldest_first(self):
        ids = [(await self.store.add_room_message("lobby", "alice", f"m{i}"))["id"] for i in range(5)]

        latest, has_more = await self.store.room_history("lobby", limit=2)
        self.assertEqual([m["text"] for m in latest], ["m3", "m4"])
        self.assertTrue(has_more)

        older, has_more = await self.store.room_history("lobby", limit=2, before=latest[0]["id"])
        self.assertEqual([m["text"] for m in older], ["m1", "m2"])
        self.assertTrue(has_more)

        oldest, has_more = await self.store.room_history("lobby", limit=2, before=ids[1])
        self.assertEqual([m["text"] for m in oldest], ["m0"])
        self.assertFalse(has_more)

    async def test_direct_messages_are_stored_but_not_in_room_history(self):
        dm = await self.store.add_dm("alice", "Bob", "secret")
        self.assertEqual(dm["username"], "alice")
        self.assertEqual(dm["to"], "Bob")
        self.assertIsInstance(dm["id"], int)
        messages, _ = await self.store.room_history("lobby")
        self.assertEqual(messages, [])

    def test_dm_key_is_order_and_case_insensitive(self):
        self.assertEqual(dm_key("Bob", "alice"), dm_key("alice", "bob"))
        self.assertEqual(dm_key("alice", "bob"), "alice:bob")

    async def test_concurrent_writes_are_serialised(self):
        results = await asyncio.gather(*(self.store.add_room_message("lobby", "alice", str(i)) for i in range(20)))
        self.assertEqual(len({r["id"] for r in results}), 20)
        messages, _ = await self.store.room_history("lobby", limit=100)
        self.assertEqual(len(messages), 20)


class StoreFileTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_attachment_metadata_survives_the_content_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chat.db"
            with sqlite3.connect(path) as raw:
                for version, migration in enumerate(MIGRATIONS[:3], start=1):
                    raw.executescript(migration)
                    raw.execute(f"PRAGMA user_version = {version}")
                raw.execute(
                    "INSERT INTO attachments VALUES (?, ?, ?, ?, ?, ?)",
                    ("old", "alice", "old.txt", "text/plain", 3, "2026-11-10T00:00:00+00:00"),
                )
            store = Store(path)
            try:
                existing = await store.get_attachment("old", include_content=True)
                self.assertEqual(existing["name"], "old.txt")
                self.assertIsNone(existing["content"])
                await store.preserve_attachment("old", b"old")
                self.assertEqual((await store.get_attachment("old", include_content=True))["content"], b"old")
            finally:
                await store.close()

    async def test_uploaded_bytes_survive_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chat.db"
            store = Store(path)
            content = b"persisted upload"
            await store.create_attachment("file", "alice", "note.txt", "text/plain", len(content), content=content)
            await store.close()

            reopened = Store(path)
            try:
                saved = await reopened.get_attachment("file", include_content=True)
                self.assertEqual(saved["content"], content)
                self.assertNotIn("content", await reopened.get_attachment("file"))
            finally:
                await reopened.close()

    async def test_messages_survive_reopen_and_schema_is_versioned(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "chat.db"
            store = Store(path)
            await store.add_room_message("lobby", "alice", "persisted")
            await store.close()

            reopened = Store(path)
            messages, _ = await reopened.room_history("lobby")
            await reopened.close()
            self.assertEqual([m["text"] for m in messages], ["persisted"])

            with sqlite3.connect(path) as raw:
                self.assertGreaterEqual(raw.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(raw.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            raw.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

