"""Integration tests: message IDs and room history over real TCP sockets."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from chat.server import ChatServer
from chat.store import Store


class Client:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, **item):
        self.writer.write((json.dumps(item) + "\n").encode())
        await self.writer.drain()

    async def expect(self, kind):
        while True:
            line = await asyncio.wait_for(self.reader.readline(), 3)
            assert line, f"Connection closed before {kind}"
            item = json.loads(line)
            if item["type"] == kind:
                return item

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class HistoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = Path(self.folder.name) / "chat.db"
        await self.start_server()

    async def start_server(self):
        self.chat = ChatServer(store=Store(self.db_path))
        self.server = await asyncio.start_server(self.chat.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop_server(self):
        self.server.close()
        await self.server.wait_closed()
        await self.chat.close()

    async def asyncTearDown(self):
        await self.stop_server()
        self.folder.cleanup()

    async def connect(self, name):
        client = Client(*await asyncio.open_connection("127.0.0.1", self.port))
        await client.send(type="hello", username=name)
        await client.expect("welcome")
        return client

    async def test_messages_and_dms_carry_server_ids(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.send(type="message", text="first")
        first = await bob.expect("message")
        await alice.send(type="message", text="second")
        second = await bob.expect("message")
        self.assertIsInstance(first["id"], int)
        self.assertGreater(second["id"], first["id"])

        await alice.send(type="dm", to="bob", text="psst")
        self.assertIsInstance((await bob.expect("dm"))["id"], int)
        await alice.close()
        await bob.close()

    async def test_late_joiner_receives_recent_room_history_after_welcome(self):
        alice = await self.connect("alice")
        await alice.expect("history")  # alice's own (empty) lobby history
        for text in ("one", "two", "three"):
            await alice.send(type="message", text=text)
            await alice.expect("message")

        bob = await self.connect("bob")
        history = await bob.expect("history")
        self.assertEqual(history["room"], "lobby")
        self.assertEqual([m["text"] for m in history["messages"]], ["one", "two", "three"])
        self.assertTrue(all(m["username"] == "alice" for m in history["messages"]))
        self.assertFalse(history["has_more"])
        await alice.close()
        await bob.close()

    async def test_joining_a_room_sends_that_rooms_history(self):
        alice = await self.connect("alice")
        await alice.send(type="join", room="study")
        await alice.expect("joined")
        await alice.send(type="message", text="study note")
        await alice.expect("message")

        bob = await self.connect("bob")
        await bob.expect("history")  # lobby
        await bob.send(type="join", room="study")
        await bob.expect("joined")
        history = await bob.expect("history")
        self.assertEqual(history["room"], "study")
        self.assertEqual([m["text"] for m in history["messages"]], ["study note"])
        await alice.close()
        await bob.close()

    async def test_history_request_pages_backwards(self):
        self.chat.history_limit = 2
        alice = await self.connect("alice")
        await alice.expect("history")
        for i in range(5):
            await alice.send(type="message", text=f"m{i}")
            await alice.expect("message")

        await alice.send(type="history")
        latest = await alice.expect("history")
        self.assertEqual([m["text"] for m in latest["messages"]], ["m3", "m4"])
        self.assertTrue(latest["has_more"])

        await alice.send(type="history", before=latest["messages"][0]["id"])
        older = await alice.expect("history")
        self.assertEqual([m["text"] for m in older["messages"]], ["m1", "m2"])
        self.assertEqual(older["before"], latest["messages"][0]["id"])
        await alice.close()

    async def test_invalid_history_requests_are_rejected(self):
        alice = await self.connect("alice")
        await alice.send(type="history", before="abc")
        self.assertIn("before", (await alice.expect("error"))["text"])
        await alice.send(type="history", room="bad room!")
        self.assertIn("Room", (await alice.expect("error"))["text"])
        await alice.close()

    async def test_room_history_survives_a_server_restart(self):
        alice = await self.connect("alice")
        await alice.send(type="message", text="before restart")
        await alice.expect("message")
        await alice.close()
        await self.stop_server()

        await self.start_server()
        bob = await self.connect("bob")
        history = await bob.expect("history")
        self.assertEqual([m["text"] for m in history["messages"]], ["before restart"])
        await bob.close()

    async def test_dm_history_is_never_served_without_accounts(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.send(type="dm", to="bob", text="private")
        await bob.expect("dm")
        await bob.send(type="history", room="lobby")
        history = await bob.expect("history")
        self.assertNotIn("private", [m["text"] for m in history["messages"]])
        await alice.close()
        await bob.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

