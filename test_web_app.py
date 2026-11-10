"""Browser gateway integration tests against real TCP sockets."""

import asyncio
import re
import unittest

from aiohttp import ClientSession, web

from chat_server import ChatServer, MAX_LINE
from web_app import create_web_app


async def receive_kind(socket, kind):
    while True:
        item = await asyncio.wait_for(socket.receive_json(), 3)
        if item["type"] == kind:
            return item


class GatewayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        chat = ChatServer()
        self.tcp = await asyncio.start_server(chat.handle, "127.0.0.1", 0, limit=MAX_LINE)
        tcp_port = self.tcp.sockets[0].getsockname()[1]
        self.runner = web.AppRunner(create_web_app("127.0.0.1", tcp_port))
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

    async def test_two_browser_clients_share_tcp_chat(self):
        async with self.session.get(self.base) as response:
            self.assertEqual(response.status, 200)
            html = await response.text()
            self.assertIn("ClayChat", html)
            for path in re.findall(r'/(?:assets/[^" ]+)', html):
                async with self.session.get(self.base + path) as asset:
                    self.assertEqual(asset.status, 200)
                    self.assertGreater(len(await asset.read()), 100)
        async with self.session.get(self.base + "/healthz") as response:
            self.assertEqual((await response.json())["status"], "ok")

        alice = await self.session.ws_connect(self.base + "/ws")
        bob = await self.session.ws_connect(self.base + "/ws")
        try:
            await asyncio.gather(receive_kind(alice, "info"), receive_kind(bob, "info"))
            await alice.send_json({"type": "hello", "username": "alice"})
            await receive_kind(alice, "welcome")
            await bob.send_json({"type": "hello", "username": "bob"})
            await receive_kind(bob, "welcome")
            await receive_kind(alice, "presence")
            await alice.send_json({"type": "message", "text": "Hello from the browser"})
            a, b = await asyncio.gather(receive_kind(alice, "message"), receive_kind(bob, "message"))
            self.assertEqual(a["text"], b["text"])
            await bob.send_json({"type": "dm", "to": "alice", "text": "Private browser DM"})
            self.assertEqual((await receive_kind(alice, "dm"))["text"], "Private browser DM")
            print("Two browser WebSockets exchanged messages through the TCP server")
        finally:
            await alice.close()
            await bob.close()

    async def test_rejects_cross_origin_websocket(self):
        async with self.session.get(self.base + "/ws", headers={"Origin": "https://wrong.example"}) as response:
            self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
