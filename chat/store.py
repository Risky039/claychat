"""SQLite or PostgreSQL persistence for chat data.

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

# Each entry upgrades the schema by one version.
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
    """
    CREATE TABLE attachments (
        id TEXT PRIMARY KEY,
        uploader TEXT NOT NULL,
        filename TEXT NOT NULL,
        mime TEXT NOT NULL,
        size INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    ALTER TABLE messages ADD COLUMN attachment_id TEXT REFERENCES attachments(id);
    CREATE TABLE reactions (
        message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        username_lower TEXT NOT NULL,
        username TEXT NOT NULL,
        emoji TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (message_id, username_lower, emoji)
    );
    CREATE INDEX idx_reactions_msg ON reactions (message_id);
    CREATE TABLE read_cursors (
        scope TEXT NOT NULL,
        username_lower TEXT NOT NULL,
        username TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (scope, username_lower)
    );
    """,
)


def dm_key(first, second):
    """Stable conversation key for two users, independent of order and case."""
    return ":".join(sorted((first.lower(), second.lower())))


def _attachment_dict(row):
    if not row or row[0] is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "mime": row[2],
        "size": row[3],
        "url": f"/api/uploads/{row[0]}",
    }


def _enrich_messages(conn, items):
    if not items:
        return items
    ids = [item["id"] for item in items]
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT message_id, emoji, username FROM reactions WHERE message_id IN ({placeholders}) ORDER BY username_lower",
        ids,
    ).fetchall()
    by_msg = {}
    for msg_id, emoji, username in rows:
        by_msg.setdefault(msg_id, {}).setdefault(emoji, []).append(username)
    for item in items:
        if item["id"] in by_msg:
            item["reactions"] = by_msg[item["id"]]
    return items


class StoreError(RuntimeError):
    """A database error safe to log without including connection details."""


def _postgres_error_reason(error):
    """Classify driver errors without logging a URI, credential, or SQL."""
    detail = str(error).lower()
    for markers, reason in (
        (("tenant or user not found", "tenant not found"), "pooler could not find the project or user"),
        (("password authentication failed", "wrong password", "no password supplied"), "database password rejected or missing"),
        (("certificate", "ssl error", "tls error", "does not support ssl"), "database TLS verification or negotiation failed"),
        (("invalid percent-encoded", "invalid uri", "missing \"=\""), "invalid database connection string"),
        (("could not translate host name", "name or service not known"), "database hostname could not be resolved"),
        (("timeout expired", "timed out"), "database connection timed out"),
        (("connection refused", "network is unreachable", "no route to host"), "database network connection failed"),
        (("permission denied", "insufficient privilege"), "database role lacks required permissions"),
    ):
        if any(marker in detail for marker in markers):
            return reason
    return type(error).__name__


class Store:
    def __init__(self, path=":memory:", *, database_url=""):
        self.path = str(path)
        self._database_url = database_url
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-store")
        self._conn = None

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._call, fn, args)

    def _call(self, fn, args):
        if self._database_url:
            from chat import postgres

            try:
                if self._conn is None or self._conn.closed:
                    self._conn = postgres.connect(self._database_url, MIGRATIONS)
                with self._conn.transaction():
                    return fn(self._conn, *args)
            except postgres.psycopg.Error as error:
                raise StoreError(f"PostgreSQL request failed ({_postgres_error_reason(error)})") from None

        if self._conn is None:
            self._conn = self._connect_sqlite()
        with self._conn:
            return fn(self._conn, *args)

    def _connect_sqlite(self):
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
        if self._conn is not None:
            await asyncio.get_running_loop().run_in_executor(self._executor, self._conn.close)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def create_attachment(self, att_id, uploader, filename, mime, size):
        def insert(conn):
            created = now_iso()
            conn.execute(
                "INSERT INTO attachments (id, uploader, filename, mime, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (att_id, uploader, filename, mime, size, created),
            )
            return {
                "id": att_id,
                "name": filename,
                "mime": mime,
                "size": size,
                "url": f"/api/uploads/{att_id}",
            }

        return await self._run(insert)

    async def get_attachment(self, att_id):
        def select(conn):
            row = conn.execute(
                "SELECT id, filename, mime, size FROM attachments WHERE id = ?",
                (att_id,),
            ).fetchone()
            return _attachment_dict(row)

        return await self._run(select)

    async def add_room_message(self, room, author, text, attachment_id=None):
        def insert(conn):
            created = now_iso()
            att = None
            if attachment_id is not None:
                att_row = conn.execute(
                    "SELECT id, filename, mime, size FROM attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
                if att_row is None:
                    raise ValueError("Attachment not found")
                att = _attachment_dict(att_row)
            message_id = conn.execute(
                "INSERT INTO messages (room, author, text, created_at, attachment_id) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (room, author, text, created, attachment_id),
            ).fetchone()[0]
            result = {"id": message_id, "room": room, "username": author, "text": text, "time": created}
            if att is not None:
                result["attachment"] = att
            return result

        return await self._run(insert)

    async def add_dm(self, author, recipient, text, attachment_id=None):
        def insert(conn):
            created = now_iso()
            att = None
            if attachment_id is not None:
                att_row = conn.execute(
                    "SELECT id, filename, mime, size FROM attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
                if att_row is None:
                    raise ValueError("Attachment not found")
                att = _attachment_dict(att_row)
            message_id = conn.execute(
                "INSERT INTO messages (dm_key, author, recipient, text, created_at, attachment_id) "
                "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (dm_key(author, recipient), author, recipient, text, created, attachment_id),
            ).fetchone()[0]
            result = {"id": message_id, "username": author, "to": recipient, "text": text, "time": created}
            if att is not None:
                result["attachment"] = att
            return result

        return await self._run(insert)

    async def get_message(self, message_id):
        def select(conn):
            row = conn.execute(
                "SELECT id, room, dm_key, author, recipient, text, created_at, edited_at, deleted_at "
                "FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "room": row[1],
                "dm_key": row[2],
                "username": row[3],
                "to": row[4],
                "text": row[5],
                "time": row[6],
                "edited_at": row[7],
                "deleted_at": row[8],
            }

        return await self._run(select)

    def _active_message_for_update(self, conn, message_id):
        query = "SELECT id, room, author, recipient FROM messages WHERE id = ? AND deleted_at IS NULL"
        if self._database_url:
            query += " FOR UPDATE"
        row = conn.execute(query, (message_id,)).fetchone()
        if row is None:
            raise LookupError("Message not found")
        return row

    async def edit_message(self, message_id, actor_username, new_text):
        def update(conn):
            row = self._active_message_for_update(conn, message_id)
            if row[2].lower() != actor_username.lower():
                raise PermissionError("Only the message author can edit this message")
            edited = now_iso()
            conn.execute(
                "UPDATE messages SET text = ?, edited_at = ? WHERE id = ?",
                (new_text, edited, message_id),
            )
            result = {"id": row[0], "username": row[2], "text": new_text, "edited_at": edited}
            if row[1] is not None:
                result["room"] = row[1]
            else:
                result["to"] = row[3]
            return result

        return await self._run(update)

    async def delete_message(self, message_id, actor_username):
        def delete(conn):
            row = self._active_message_for_update(conn, message_id)
            if row[2].lower() != actor_username.lower():
                raise PermissionError("Only the message author can delete this message")
            deleted = now_iso()
            conn.execute(
                "UPDATE messages SET text = '', deleted_at = ? WHERE id = ?",
                (deleted, message_id),
            )
            result = {"id": row[0], "username": row[2], "deleted_at": deleted}
            if row[1] is not None:
                result["room"] = row[1]
            else:
                result["to"] = row[3]
            return result

        return await self._run(delete)

    async def toggle_reaction(self, message_id, username, emoji):
        def toggle(conn):
            row = self._active_message_for_update(conn, message_id)
            lower = username.lower()
            existing = conn.execute(
                "SELECT 1 FROM reactions WHERE message_id = ? AND username_lower = ? AND emoji = ?",
                (message_id, lower, emoji),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM reactions WHERE message_id = ? AND username_lower = ? AND emoji = ?",
                    (message_id, lower, emoji),
                )
            else:
                conn.execute(
                    "INSERT INTO reactions (message_id, username_lower, username, emoji, created_at) VALUES (?, ?, ?, ?, ?)",
                    (message_id, lower, username, emoji, now_iso()),
                )
            all_rows = conn.execute(
                "SELECT emoji, username FROM reactions WHERE message_id = ? ORDER BY username_lower",
                (message_id,),
            ).fetchall()
            reactions = {}
            for em, uname in all_rows:
                reactions.setdefault(em, []).append(uname)
            result = {"id": row[0], "reactions": reactions}
            if row[1] is not None:
                result["room"] = row[1]
            else:
                result["username"] = row[2]
                result["to"] = row[3]
            return result

        return await self._run(toggle)

    async def mark_read(self, message_id, username):
        def update(conn):
            row = conn.execute(
                "SELECT id, room, dm_key, author, recipient, deleted_at FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None or row[5] is not None:
                raise LookupError("Message not found")
            scope = f"room:{row[1]}" if row[1] is not None else f"dm:{row[2]}"
            lower = username.lower()
            updated = now_iso()
            conn.execute(
                """
                INSERT INTO read_cursors (scope, username_lower, username, message_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope, username_lower) DO UPDATE SET
                    message_id = CASE WHEN excluded.message_id > read_cursors.message_id THEN excluded.message_id ELSE read_cursors.message_id END,
                    updated_at = excluded.updated_at
                """,
                (scope, lower, username, message_id, updated),
            )
            result = {"id": row[0], "username": username}
            if row[1] is not None:
                result["room"] = row[1]
            else:
                result["author"] = row[3]
                result["to"] = row[4]
            return result

        return await self._run(update)

    async def room_history(self, room, limit=50, before=None):
        """Return up to ``limit`` messages older than ``before`` (oldest first) and a has-more flag."""

        def select(conn):
            query = (
                "SELECT m.id, m.room, m.author, m.text, m.created_at, m.edited_at, "
                "a.id, a.filename, a.mime, a.size "
                "FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id "
                "WHERE m.room = ? AND m.deleted_at IS NULL"
            )
            params = [room]
            if before is not None:
                query += " AND m.id < ?"
                params.append(before)
            query += " ORDER BY m.id DESC LIMIT ?"
            params.append(limit + 1)
            rows = conn.execute(query, params).fetchall()
            has_more = len(rows) > limit
            items = []
            for r in reversed(rows[:limit]):
                item = {"id": r[0], "room": r[1], "username": r[2], "text": r[3], "time": r[4]}
                if r[5] is not None:
                    item["edited_at"] = r[5]
                att = _attachment_dict(r[6:10])
                if att is not None:
                    item["attachment"] = att
                items.append(item)
            return _enrich_messages(conn, items), has_more

        return await self._run(select)

    async def dm_history(self, user_a, user_b, limit=50, before=None):
        """Return up to ``limit`` DMs between ``user_a`` and ``user_b`` (oldest first) and a has-more flag."""

        def select(conn):
            query = (
                "SELECT m.id, m.author, m.recipient, m.text, m.created_at, m.edited_at, "
                "a.id, a.filename, a.mime, a.size "
                "FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id "
                "WHERE m.dm_key = ? AND m.deleted_at IS NULL"
            )
            params = [dm_key(user_a, user_b)]
            if before is not None:
                query += " AND m.id < ?"
                params.append(before)
            query += " ORDER BY m.id DESC LIMIT ?"
            params.append(limit + 1)
            rows = conn.execute(query, params).fetchall()
            has_more = len(rows) > limit
            items = []
            for r in reversed(rows[:limit]):
                item = {"id": r[0], "username": r[1], "to": r[2], "text": r[3], "time": r[4]}
                if r[5] is not None:
                    item["edited_at"] = r[5]
                att = _attachment_dict(r[6:10])
                if att is not None:
                    item["attachment"] = att
                items.append(item)
            return _enrich_messages(conn, items), has_more

        return await self._run(select)

    async def create_user(self, username, password):
        pw_hash = hash_password(password)

        def insert(conn):
            created = now_iso()
            row = conn.execute(
                "INSERT INTO users (username, username_lower, password_hash, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (username_lower) DO NOTHING RETURNING id",
                (username, username.lower(), pw_hash, created),
            ).fetchone()
            if row is None:
                raise ValueError("Username is already registered")
            return {"id": row[0], "username": username, "created_at": created}

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
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))

        await self._run(delete)
