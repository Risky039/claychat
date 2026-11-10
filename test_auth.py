"""Unit and integration tests for Phase 1: accounts, sessions, rate limiting, and security."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, CookieJar, web

from chat.auth import hash_password, hash_token, new_session_token, verify_password
from chat.config import Settings
from chat.protocol import MAX_LINE
from chat.ratelimit import RateLimiter
from chat.server import ChatServer
from chat.store import Store
from web_app import create_web_app


class PasswordAndTokenUnitTest(unittest.TestCase):
    def test_scrypt_hash_and_verify(self):
        encoded = hash_password("correct horse battery staple")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertFalse(verify_password("correct horse battery staple", "malformed"))

    def test_session_token_generation_and_hashing(self):
        token1 = new_session_token()
        token2 = new_session_token()
        self.assertNotEqual(token1, token2)
        self.assertGreaterEqual(len(token1), 40)
        self.assertEqual(hash_token(token1), hash_token(token1))
        self.assertNotEqual(hash_token(token1), hash_token(token2))


class RateLimiterUnitTest(unittest.TestCase):
    def test_token_bucket_allows_burst_and_refills(self):
        clock = [100.0]
        limiter = RateLimiter(rate=2.0, capacity=3.0, clock=lambda: clock[0])
        self.assertTrue(limiter.allow("alice"))
        self.assertTrue(limiter.allow("alice"))
        self.assertTrue(limiter.allow("alice"))
        self.assertFalse(limiter.allow("alice"))
        # Other keys are independent
        self.assertTrue(limiter.allow("bob"))
        # Advance 0.5s -> 1 token refilled
        clock[0] += 0.5
        self.assertTrue(limiter.allow("alice"))
        self.assertFalse(limiter.allow("alice"))


class StoreAccountTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")

    async def asyncTearDown(self):
        await self.store.close()

    async def test_register_authenticate_and_sessions(self):
        user = await self.store.create_user("Alice", "secret12345")
        self.assertEqual(user["username"], "Alice")
        with self.assertRaises(ValueError):
            await self.store.create_user("alice", "otherpass123")

        authed = await self.store.authenticate_user("ALICE", "secret12345")
        self.assertEqual(authed["username"], "Alice")
        self.assertIsNone(await self.store.authenticate_user("Alice", "wrongpass"))
        self.assertIsNone(await self.store.authenticate_user("unknown", "secret12345"))

        token = await self.store.create_session(user["id"])
        session_user = await self.store.user_by_token(token)
        self.assertEqual(session_user["username"], "Alice")

        await self.store.revoke_session(token)
        self.assertIsNone(await self.store.user_by_token(token))

    async def test_dm_history_pagination(self):
        for i in range(4):
            await self.store.add_dm("Alice", "Bob", f"dm-{i}")
        latest, has_more = await self.store.dm_history("bob", "alice", limit=2)
        self.assertEqual([m["text"] for m in latest], ["dm-2", "dm-3"])
        self.assertTrue(has_more)

        older, has_more = await self.store.dm_history("alice", "bob", limit=2, before=latest[0]["id"])
        self.assertEqual([m["text"] for m in older], ["dm-0", "dm-1"])
        self.assertFalse(has_more)


class TcpClient:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, **item):
        self.writer.write((json.dumps(item) + "\n").encode())
        await self.writer.drain()

    async def expect(self, kind, timeout=3):
        while True:
            line = await asyncio.wait_for(self.reader.readline(), timeout)
            assert line, f"Connection closed before {kind}"
            item = json.loads(line)
            if item["type"] == kind:
                return item

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class TcpAuthAndSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(hello_timeout=0.35, msg_rate=2.0, msg_burst=2.0)
        self.chat = ChatServer(store=self.store, settings=self.settings)
        self.server = await asyncio.start_server(self.chat.handle, "127.0.0.1", 0, limit=MAX_LINE)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.chat.close()

    async def test_registered_nick_requires_valid_token_and_unlocks_dm_history(self):
        user = await self.store.create_user("Alice", "password123")
        token = await self.store.create_session(user["id"])
        await self.store.add_dm("Alice", "bob", "saved secret")

        # Guest cannot impersonate registered user "Alice"
        impostor = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await impostor.expect("info")
        await impostor.send(type="hello", username="alice")
        err = await impostor.expect("error")
        self.assertIn("registered", err["text"].lower())
        await impostor.close()

        # Real Alice connects with session token
        alice = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await alice.expect("info")
        await alice.send(type="hello", token=token)
        welcome = await alice.expect("welcome")
        self.assertEqual(welcome["username"], "Alice")
        self.assertTrue(welcome["authenticated"])

        # Authenticated Alice can fetch DM history with bob
        await alice.send(type="dm_history", with_user="bob")
        dm_hist = await alice.expect("dm_history")
        self.assertEqual(dm_hist["with_user"], "bob")
        self.assertEqual([m["text"] for m in dm_hist["messages"]], ["saved secret"])

        # Unauthenticated guest bob cannot fetch DM history
        bob = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await bob.expect("info")
        await bob.send(type="hello", username="bob")
        await bob.expect("welcome")
        await bob.send(type="dm_history", with_user="Alice")
        bob_err = await bob.expect("error")
        self.assertIn("sign in", bob_err["text"].lower())

        await alice.close()
        await bob.close()

    async def test_hello_timeout_disconnects_silent_client(self):
        client = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await client.expect("info")
        err = await client.expect("error", timeout=2)
        self.assertIn("timeout", err["text"].lower())
        eof = await asyncio.wait_for(client.reader.readline(), 2)
        self.assertEqual(eof, b"")
        await client.close()

    async def test_message_rate_limit_blocks_flood(self):
        client = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await client.expect("info")
        await client.send(type="hello", username="alice")
        await client.expect("welcome")
        await client.expect("history")

        await client.send(type="message", text="msg 1")
        await client.expect("message")
        await client.send(type="message", text="msg 2")
        await client.expect("message")
        await client.send(type="message", text="msg 3")
        err = await client.expect("error")
        self.assertIn("slow down", err["text"].lower())
        await client.close()


class WebAuthGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        db_path = Path(self.folder.name) / "chat.db"
        self.store = Store(db_path)
        self.settings = Settings(db_path=str(db_path), invite_code="join-secret")
        self.chat = ChatServer(store=self.store, settings=self.settings)
        self.tcp = await asyncio.start_server(self.chat.handle, "127.0.0.1", 0, limit=MAX_LINE)
        tcp_port = self.tcp.sockets[0].getsockname()[1]
        self.runner = web.AppRunner(
            create_web_app("127.0.0.1", tcp_port, store=self.store, settings=self.settings)
        )
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        web_port = self.site._server.sockets[0].getsockname()[1]
        self.base = f"http://127.0.0.1:{web_port}"
        self.session = ClientSession(cookie_jar=CookieJar(unsafe=True))

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        self.tcp.close()
        await self.tcp.wait_closed()
        await self.chat.close()
        self.folder.cleanup()

    async def test_register_login_cookie_websocket_and_logout_flow(self):
        # Invite code required when configured
        async with self.session.post(
            self.base + "/api/register",
            json={"username": "Alice", "password": "password123", "invite_code": "wrong"},
        ) as resp:
            self.assertEqual(resp.status, 403)

        # Cross-origin POST rejected
        async with self.session.post(
            self.base + "/api/register",
            headers={"Origin": "https://evil.example"},
            json={"username": "Alice", "password": "password123", "invite_code": "join-secret"},
        ) as resp:
            self.assertEqual(resp.status, 403)

        # Valid registration sets HttpOnly session cookie and returns user
        async with self.session.post(
            self.base + "/api/register",
            json={"username": "Alice", "password": "password123", "invite_code": "join-secret"},
        ) as resp:
            self.assertEqual(resp.status, 201)
            body = await resp.json()
            self.assertEqual(body["username"], "Alice")
            self.assertIn("token", body)

        # /api/me reflects active cookie session
        async with self.session.get(self.base + "/api/me") as resp:
            self.assertEqual(resp.status, 200)
            me = await resp.json()
            self.assertEqual(me["username"], "Alice")
            self.assertTrue(me["authenticated"])

        # WebSocket connects using the HttpOnly cookie automatically even if client sends empty hello
        ws = await self.session.ws_connect(self.base + "/ws")
        try:
            await ws.receive_json()  # info
            await ws.send_json({"type": "hello"})
            welcome = await ws.receive_json()
            self.assertEqual(welcome["type"], "welcome")
            self.assertEqual(welcome["username"], "Alice")
            self.assertTrue(welcome["authenticated"])
        finally:
            await ws.close()

        # Logout clears session
        async with self.session.post(self.base + "/api/logout") as resp:
            self.assertEqual(resp.status, 200)
        async with self.session.get(self.base + "/api/me") as resp:
            me = await resp.json()
            self.assertFalse(me["authenticated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
