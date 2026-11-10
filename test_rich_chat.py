"""Unit and integration tests for Phase 2: typing, edit/delete, reactions, read receipts, and uploads."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, FormData, web

from chat.config import Settings
from chat.protocol import MAX_LINE
from chat.server import ChatServer
from chat.store import Store
from web_app import create_web_app

# Minimal valid 1x1 PNG
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


class RichChatTcpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(msg_rate=20.0, msg_burst=20.0)
        self.chat = ChatServer(store=self.store, settings=self.settings)
        self.server = await asyncio.start_server(self.chat.handle, "127.0.0.1", 0, limit=MAX_LINE)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.chat.close()

    async def connect(self, name):
        client = TcpClient(*await asyncio.open_connection("127.0.0.1", self.port))
        await client.expect("info")
        await client.send(type="hello", username=name)
        await client.expect("welcome")
        await client.expect("history")
        return client

    async def test_typing_indicator_room_and_dm(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.expect("presence")

        await alice.send(type="typing")
        ev = await bob.expect("typing")
        self.assertEqual(ev["room"], "lobby")
        self.assertEqual(ev["username"], "alice")

        # Wait or reset typing cooldown for DM typing test
        self.chat.typing_limiter._buckets.clear()
        await bob.send(type="typing", to="alice")
        dm_ev = await alice.expect("typing")
        self.assertEqual(dm_ev["to"], "alice")
        self.assertEqual(dm_ev["username"], "bob")

        await alice.close()
        await bob.close()

    async def test_edit_and_delete_permissions_and_history(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.expect("presence")

        await alice.send(type="message", text="original")
        msg_a, msg_b = await asyncio.gather(alice.expect("message"), bob.expect("message"))
        msg_id = msg_a["id"]

        # Bob cannot edit Alice's message
        await bob.send(type="edit", id=msg_id, text="hacked")
        err = await bob.expect("error")
        self.assertIn("author", err["text"].lower())

        # Alice edits her own message
        await alice.send(type="edit", id=msg_id, text="updated text")
        up_a, up_b = await asyncio.gather(
            alice.expect("message_updated"), bob.expect("message_updated")
        )
        self.assertEqual(up_b["id"], msg_id)
        self.assertEqual(up_b["text"], "updated text")
        self.assertIn("T", up_b["edited_at"])

        # History reflects edited text and edited_at
        await bob.send(type="history", room="lobby")
        hist = await bob.expect("history")
        self.assertEqual(hist["messages"][0]["text"], "updated text")
        self.assertIsNotNone(hist["messages"][0]["edited_at"])

        # Bob cannot delete Alice's message
        await bob.send(type="delete", id=msg_id)
        err2 = await bob.expect("error")
        self.assertIn("author", err2["text"].lower())

        # Alice deletes her message
        await alice.send(type="delete", id=msg_id)
        del_a, del_b = await asyncio.gather(
            alice.expect("message_deleted"), bob.expect("message_deleted")
        )
        self.assertEqual(del_b["id"], msg_id)

        # Deleted message is omitted from future room history
        await bob.send(type="history", room="lobby")
        hist_after = await bob.expect("history")
        self.assertEqual(hist_after["messages"], [])

        await alice.close()
        await bob.close()

    async def test_reactions_toggle_and_appear_in_history(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.expect("presence")

        await alice.send(type="message", text="react to me")
        msg, _ = await asyncio.gather(alice.expect("message"), bob.expect("message"))
        msg_id = msg["id"]

        # Unsupported emoji rejected
        await bob.send(type="react", id=msg_id, emoji="🦖")
        err = await bob.expect("error")
        self.assertIn("emoji", err["text"].lower())

        # Bob adds 👍
        await bob.send(type="react", id=msg_id, emoji="👍")
        r1_a, r1_b = await asyncio.gather(
            alice.expect("reactions_updated"), bob.expect("reactions_updated")
        )
        self.assertEqual(r1_a["reactions"], {"👍": ["bob"]})

        # Alice also adds 👍
        await alice.send(type="react", id=msg_id, emoji="👍")
        r2_a, _ = await asyncio.gather(
            alice.expect("reactions_updated"), bob.expect("reactions_updated")
        )
        self.assertEqual(r2_a["reactions"], {"👍": ["alice", "bob"]})

        # History includes reactions map
        await bob.send(type="history", room="lobby")
        hist = await bob.expect("history")
        self.assertEqual(hist["messages"][0]["reactions"], {"👍": ["alice", "bob"]})

        # Bob toggles 👍 off
        await bob.send(type="react", id=msg_id, emoji="👍")
        r3_a, _ = await asyncio.gather(
            alice.expect("reactions_updated"), bob.expect("reactions_updated")
        )
        self.assertEqual(r3_a["reactions"], {"👍": ["alice"]})

        await alice.close()
        await bob.close()

    async def test_read_receipts_broadcast_to_room_and_dm(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.expect("presence")

        await alice.send(type="message", text="please read")
        msg, _ = await asyncio.gather(alice.expect("message"), bob.expect("message"))

        await bob.send(type="read", id=msg["id"])
        receipt = await alice.expect("read_receipt")
        self.assertEqual(receipt["room"], "lobby")
        self.assertEqual(receipt["username"], "bob")
        self.assertEqual(receipt["id"], msg["id"])

        # DM read receipt
        await alice.send(type="dm", to="bob", text="private note")
        dm_a, dm_b = await asyncio.gather(alice.expect("dm"), bob.expect("dm"))
        await bob.send(type="read", id=dm_b["id"])
        dm_receipt = await alice.expect("read_receipt")
        self.assertEqual(dm_receipt["username"], "bob")
        self.assertEqual(dm_receipt["id"], dm_b["id"])

        await alice.close()
        await bob.close()


class UploadGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base_dir = Path(self.folder.name)
        self.store = Store(base_dir / "chat.db")
        self.settings = Settings(
            db_path=str(base_dir / "chat.db"),
            upload_dir=str(base_dir / "uploads"),
        )
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
        self.session = ClientSession()

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        self.tcp.close()
        await self.tcp.wait_closed()
        await self.chat.close()
        self.folder.cleanup()

    async def test_upload_magic_byte_validation_download_and_chat_attachment(self):
        # Executable / unknown binary rejected
        bad_form = FormData()
        bad_form.add_field("file", b"MZ\x90\x00not-an-image", filename="evil.exe")
        async with self.session.post(self.base + "/api/uploads", data=bad_form) as resp:
            self.assertEqual(resp.status, 400)

        # Valid PNG accepted
        good_form = FormData()
        good_form.add_field("file", TINY_PNG, filename="pixel.png", content_type="image/png")
        async with self.session.post(self.base + "/api/uploads", data=good_form) as resp:
            self.assertEqual(resp.status, 201)
            att = await resp.json()
            self.assertEqual(att["mime"], "image/png")
            self.assertEqual(att["name"], "pixel.png")
            self.assertTrue(att["url"].startswith("/api/uploads/"))

        # Download serves bytes with nosniff
        async with self.session.get(self.base + att["url"]) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(await resp.read(), TINY_PNG)

        # Send a chat message referencing attachment_id
        ws = await self.session.ws_connect(self.base + "/ws")
        try:
            await ws.receive_json()  # info
            await ws.send_json({"type": "hello", "username": "alice"})
            await ws.receive_json()  # welcome
            await ws.receive_json()  # history
            await ws.send_json({"type": "message", "text": "Here is an image", "attachment_id": att["id"]})
            msg = await ws.receive_json()
            self.assertEqual(msg["type"], "message")
            self.assertEqual(msg["attachment"]["id"], att["id"])
            self.assertEqual(msg["attachment"]["mime"], "image/png")
        finally:
            await ws.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
