"""SQLite persistence for chat messages, user accounts, and sessions.

All database work runs on one dedicated worker thread, so the asyncio loop never
blocks on disk I/O and the single connection is never used concurrently.
"""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chat.auth import hash_password, hash_token, new_session_token, verify_password
from chat.protocol import now_iso

# Dummy scrypt hash used when a username is not found to equalize login timing.
_DUMMY_HASH = hash_password("timing-defense-placeholder-password")

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
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        username_lower TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX idx_sessions_user ON sessions (user_id);
    """,
)


def dm_key(first, second):
    """Stable conversation key for two users, independent of order and case."""
    return ":".join(sorted((first.lower(), second.lower())))


def _room_row(row):
    return {"id": row[0], "room": row[1], "username": row[2], "text": row[3], "time": row[4]}


def _dm_row(row):
    return {"id": row[0], "username": row[1], "to": row[2], "text": row[3], "time": row[4]}


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

    async def dm_history(self, user_a, user_b, limit=50, before=None):
        """Return up to ``limit`` DMs between ``user_a`` and ``user_b`` (oldest first) and a has-more flag."""

        def select(conn):
            query = (
                "SELECT id, author, recipient, text, created_at FROM messages "
                "WHERE dm_key = ? AND deleted_at IS NULL"
            )
            params = [dm_key(user_a, user_b)]
            if before is not None:
                query += " AND id < ?"
                params.append(before)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit + 1)
            rows = conn.execute(query, params).fetchall()
            has_more = len(rows) > limit
            return [_dm_row(row) for row in reversed(rows[:limit])], has_more

        return await self._run(select)

    async def create_user(self, username, password):
        pw_hash = hash_password(password)

        def insert(conn):
            created = now_iso()
            try:
                with conn:
                    cursor = conn.execute(
                        "INSERT INTO users (username, username_lower, password_hash, created_at) VALUES (?, ?, ?, ?)",
                        (username, username.lower(), pw_hash, created),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Username is already registered") from exc
            return {"id": cursor.lastrowid, "username": username, "created_at": created}

        return await self._run(insert)

    async def user_exists(self, username):
        def check(conn):
            row = conn.execute("SELECT 1 FROM users WHERE username_lower = ?", (username.lower(),)).fetchone()
            return row is not None

        return await self._run(check)

    async def authenticate_user(self, username, password):
        def verify(conn):
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username_lower = ?",
                (username.lower(),),
            ).fetchone()
            if row is None:
                verify_password(password, _DUMMY_HASH)
                return None
            if not verify_password(password, row[2]):
                return None
            return {"id": row[0], "username": row[1], "created_at": row[3]}

        return await self._run(verify)

    async def create_session(self, user_id, ttl_days=30):
        token = new_session_token()
        digest = hash_token(token)

        def insert(conn):
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(days=ttl_days)).isoformat()
            with conn:
                conn.execute(
                    "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (digest, user_id, now.isoformat(), expires),
                )
            return token

        return await self._run(insert)

    async def user_by_token(self, token):
        digest = hash_token(token)
        if not digest:
            return None

        def select(conn):
            now = now_iso()
            row = conn.execute(
                """
                SELECT u.id, u.username, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (digest, now),
            ).fetchone()
            if row is None:
                return None
            return {"id": row[0], "username": row[1], "created_at": row[2]}

        return await self._run(select)

    async def revoke_session(self, token):
        digest = hash_token(token)
        if not digest:
            return

        def delete(conn):
            with conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))

        await self._run(delete)
