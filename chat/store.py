"""SQLite persistence for chat messages.

All database work runs on one dedicated worker thread, so the asyncio loop never
blocks on disk I/O and the single connection is never used concurrently.
"""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chat.protocol import now_iso

# Each entry upgrades the schema by one version (tracked in PRAGMA user_version).
MIGRATIONS = (
    """
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room TEXT,
        dm_key TEXT,
        author TEXT NOT NULL,
        recipient TEXT,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        edited_at TEXT,
        deleted_at TEXT,
        CHECK ((room IS NULL) <> (dm_key IS NULL))
    );
    CREATE INDEX idx_messages_room ON messages (room, id) WHERE room IS NOT NULL;
    CREATE INDEX idx_messages_dm ON messages (dm_key, id) WHERE dm_key IS NOT NULL;
    """,
)


def dm_key(first, second):
    """Stable conversation key for two users, independent of order and case."""
    return ":".join(sorted((first.lower(), second.lower())))


def _room_row(row):
    return {"id": row[0], "room": row[1], "username": row[2], "text": row[3], "time": row[4]}


class Store:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-store")
        self._conn = None

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._call, fn, args)

    def _call(self, fn, args):
        if self._conn is None:
            self._conn = self._connect()
        return fn(self._conn, *args)

    def _connect(self):
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # Schema change and version bump commit atomically.
            conn.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")
        return conn

    async def close(self):
        def shutdown(conn):
            conn.close()

        if self._conn is not None:
            await self._run(shutdown)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def add_room_message(self, room, author, text):
        def insert(conn):
            created = now_iso()
            with conn:
                cursor = conn.execute(
                    "INSERT INTO messages (room, author, text, created_at) VALUES (?, ?, ?, ?)",
                    (room, author, text, created),
                )
            return {"id": cursor.lastrowid, "room": room, "username": author, "text": text, "time": created}

        return await self._run(insert)

    async def add_dm(self, author, recipient, text):
        def insert(conn):
            created = now_iso()
            with conn:
                cursor = conn.execute(
                    "INSERT INTO messages (dm_key, author, recipient, text, created_at) VALUES (?, ?, ?, ?, ?)",
                    (dm_key(author, recipient), author, recipient, text, created),
                )
            return {"id": cursor.lastrowid, "username": author, "to": recipient, "text": text, "time": created}

        return await self._run(insert)

    async def room_history(self, room, limit=50, before=None):
        """Return up to ``limit`` messages older than ``before`` (oldest first) and a has-more flag."""

        def select(conn):
            query = "SELECT id, room, author, text, created_at FROM messages WHERE room = ? AND deleted_at IS NULL"
            params = [room]
            if before is not None:
                query += " AND id < ?"
                params.append(before)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit + 1)
            rows = conn.execute(query, params).fetchall()
            has_more = len(rows) > limit
            return [_room_row(row) for row in reversed(rows[:limit])], has_more

        return await self._run(select)
