"""Unit and integration tests for Phase 3: SSE streaming AI, room @ai mentions, and /summarize."""

import asyncio
import json
import unittest
from unittest.mock import patch

from chat.ai import parse_sse_lines
from chat.config import Settings
from chat.protocol import MAX_LINE
from chat.server import ChatServer
from chat.store import Store


class SseParserUnitTest(unittest.TestCase):
    def test_parse_sse_lines_extracts_visible_content_and_ignores_reasoning(self):
        raw_lines = [
            b": keep-alive\n",
            b'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}\n',
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
            b"\n",
            b'data: {"choices":[{"delta":{"content":" world!"}}]}\n',
            b"data: [DONE]\n",
            b'data: {"choices":[{"delta":{"content":"ignored after done"}}]}\n',
        ]
        chunks = list(parse_sse_lines(raw_lines))
        self.assertEqual(chunks, ["Hello", " world!"])


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


class SmarterAiTcpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")
        self.settings = Settings(api_key="test-key", msg_rate=20.0, msg_burst=20.0)
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

    async def test_streaming_ai_emits_deltas_then_final_ai_packet(self):
        alice = await self.connect("alice")

        def fake_stream(messages, api_key, model):
            yield "TCP "
            yield "streams "
            yield "bytes."

        with patch("chat.ai.stream_meta", side_effect=fake_stream):
            await alice.send(type="ai", text="How does TCP work?", stream=True)
            await alice.expect("ai_status")
            d1 = await alice.expect("ai_delta")
            d2 = await alice.expect("ai_delta")
            d3 = await alice.expect("ai_delta")
            final = await alice.expect("ai")
            self.assertEqual(d1["delta"] + d2["delta"] + d3["delta"], "TCP streams bytes.")
            self.assertEqual(final["text"], "TCP streams bytes.")
            self.assertEqual(final["turns"], 1)

        await alice.close()

    async def test_room_ai_mention_includes_room_context_and_broadcasts_reply(self):
        alice = await self.connect("alice")
        bob = await self.connect("bob")
        await alice.expect("presence")

        await alice.send(type="message", text="We are planning a trip to Kyoto.")
        await asyncio.gather(alice.expect("message"), bob.expect("message"))

        captured = []

        def fake_meta(messages, api_key, model):
            captured.append(messages)
            return "Kyoto is wonderful in autumn!"

        with patch("chat.ai.ask_meta", side_effect=fake_meta):
            await bob.send(type="message", text="@ai What season should we visit?")
            # First the human message is broadcast
            human_a, human_b = await asyncio.gather(alice.expect("message"), bob.expect("message"))
            self.assertEqual(human_a["username"], "bob")
            # Then Chunky's room message is saved and broadcast to both Alice and Bob
            ai_a, ai_b = await asyncio.gather(alice.expect("message"), bob.expect("message"))
            self.assertEqual(ai_a["username"], "Chunky")
            self.assertEqual(ai_b["text"], "Kyoto is wonderful in autumn!")
            self.assertTrue(any("Kyoto" in m["content"] for m in captured[0]))

        await alice.close()
        await bob.close()

    async def test_summarize_room_returns_private_summary(self):
        alice = await self.connect("alice")
        await alice.send(type="message", text="Decision 1: use SQLite WAL.")
        await alice.expect("message")
        await alice.send(type="message", text="Decision 2: use Caddy for TLS.")
        await alice.expect("message")

        with patch("chat.ai.ask_meta", return_value="Summary: SQLite WAL and Caddy TLS.") as mocked:
            await alice.send(type="summarize", count=10)
            summary = await alice.expect("ai")
            self.assertEqual(summary["kind"], "summary")
            self.assertEqual(summary["room"], "lobby")
            self.assertIn("SQLite WAL", summary["text"])
            mocked.assert_called_once()

        await alice.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

