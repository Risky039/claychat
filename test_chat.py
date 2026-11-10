"""End-to-end protocol test and reproducible two-user transcript."""

import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from chat_server import ChatServer


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

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


class ChatTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.chat = ChatServer()
        self.server = await asyncio.start_server(self.chat.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def connect(self, name):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        client = Client(reader, writer)
        await client.expect("info")
        await client.send(type="hello", username=name)
        await client.expect("welcome")
        return client

    async def test_two_users_rooms_dm_and_disconnect(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        joined = await alice.expect("presence")
        self.assertEqual(joined["username"], "bob")

        await alice.send(type="message", text="Hello, Bob!")
        to_alice, to_bob = await asyncio.gather(alice.expect("message"), bob.expect("message"))
        self.assertEqual(to_alice["text"], "Hello, Bob!")
        self.assertEqual(to_bob["text"], "Hello, Bob!")
        print(f"alice -> lobby: {to_bob['text']}")

        await bob.send(type="message", text="Hi, Alice!")
        to_alice, to_bob = await asyncio.gather(alice.expect("message"), bob.expect("message"))
        self.assertEqual(to_alice["text"], "Hi, Alice!")
        print(f"bob -> lobby: {to_alice['text']}")

        await alice.send(type="dm", to="bob", text="Private hello")
        dm_alice, dm_bob = await asyncio.gather(alice.expect("dm"), bob.expect("dm"))
        self.assertEqual(dm_bob["text"], "Private hello")
        self.assertEqual(dm_alice["to"], "bob")
        print(f"alice -> bob (DM): {dm_bob['text']}")

        await bob.send(type="join", room="study")
        self.assertEqual((await bob.expect("joined"))["room"], "study")
        self.assertEqual((await alice.expect("presence"))["action"], "left")
        await bob.send(type="users")
        self.assertEqual((await bob.expect("users"))["usernames"], ["bob"])

        await bob.close()
        await asyncio.sleep(0.05)
        self.assertNotIn("bob", self.chat.peers)
        await alice.close()

    async def test_duplicate_name_and_invalid_json(self):
        alice = await self.connect("alice")
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        other = Client(reader, writer)
        await other.expect("info")
        await other.send(type="hello", username="alice")
        self.assertIn("already", (await other.expect("error"))["text"])
        writer.write(b"not json\n")
        await writer.drain()
        self.assertIn("JSON", (await other.expect("error"))["text"])
        await other.close()
        await alice.close()

    async def test_meta_ai_command_and_missing_key(self):
        self.chat.api_key = ""
        alice = await self.connect("alice")
        await alice.send(type="ai", text="Explain TCP")
        self.assertIn("not configured", (await alice.expect("error"))["text"])
        self.chat.api_key = "test-only-key"
        with patch("chat.ai.ask_meta", return_value="TCP delivers ordered bytes") as mocked:
            await alice.send(type="ai", text="Explain TCP")
            reply = await alice.expect("ai")
            self.assertEqual(reply["text"], "TCP delivers ordered bytes")
            self.assertEqual(reply["username"], "Chunky")
            mocked.assert_called_once()
            messages, key, model = mocked.call_args.args
            self.assertEqual(messages[-1], {"role": "user", "content": "Explain TCP"})
            self.assertEqual(key, "test-only-key")
            self.assertEqual(model, self.chat.model)
        await alice.close()

    async def test_ai_remembers_followups_and_isolates_users(self):
        self.chat.api_key = "test-only-key"
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        calls = []

        def fake_meta(messages, key, model):
            calls.append(messages)
            return f"answer {len(calls)}"

        with patch("chat.ai.ask_meta", side_effect=fake_meta):
            await alice.send(type="ai", text="My name is Alice")
            self.assertEqual((await alice.expect("ai"))["text"], "answer 1")
            self.chat.peers["alice"].last_ai = 0
            await alice.send(type="ai", text="What is my name?")
            self.assertEqual((await alice.expect("ai"))["text"], "answer 2")
            self.assertEqual(calls[1][-3:], [
                {"role": "user", "content": "My name is Alice"},
                {"role": "assistant", "content": "answer 1"},
                {"role": "user", "content": "What is my name?"},
            ])
            await bob.send(type="ai", text="Hello")
            self.assertEqual((await bob.expect("ai"))["text"], "answer 3")
            self.assertEqual(len(calls[2]), 2)  # Bob receives no Alice history.
            await alice.send(type="ai_history")
            self.assertEqual((await alice.expect("ai_history"))["turns"], 2)
            await alice.send(type="ai_reset")
            await alice.expect("ai_reset")
            self.chat.peers["alice"].last_ai = 0
            await alice.send(type="ai", text="Start over")
            self.assertEqual((await alice.expect("ai"))["text"], "answer 4")
            self.assertEqual(len(calls[3]), 2)

        await bob.close()
        await alice.close()

    async def test_failed_ai_reply_does_not_enter_history(self):
        self.chat.api_key = "test-only-key"
        alice = await self.connect("alice")
        with patch("chat.ai.ask_meta", side_effect=ValueError("empty")):
            await alice.send(type="ai", text="Try")
            error = await alice.expect("error")
            self.assertEqual(error["source"], "ai")
        await alice.send(type="ai_history")
        self.assertEqual((await alice.expect("ai_history"))["turns"], 0)
        await alice.close()

    async def test_reset_discards_an_in_flight_answer(self):
        self.chat.api_key = "test-only-key"
        alice = await self.connect("alice")
        started = threading.Event()
        release = threading.Event()

        def delayed_meta(messages, key, model):
            started.set()
            release.wait(2)
            return "stale answer"

        try:
            with patch("chat.ai.ask_meta", side_effect=delayed_meta):
                await alice.send(type="ai", text="Remember this")
                await alice.expect("ai_status")
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                await alice.send(type="ai_reset")
                await alice.expect("ai_reset")
                release.set()
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(alice.reader.readline(), 0.2)
                await alice.send(type="ai_history")
                self.assertEqual((await alice.expect("ai_history"))["turns"], 0)
        finally:
            release.set()
            await alice.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
