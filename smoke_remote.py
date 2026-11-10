"""Verify two simultaneous TCP users against a running server and save evidence."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


class Connection:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, **item):
        self.writer.write((json.dumps(item) + "\n").encode())
        await self.writer.drain()

    async def receive(self, kind):
        while True:
            raw = await asyncio.wait_for(self.reader.readline(), 8)
            if not raw:
                raise RuntimeError(f"Disconnected before {kind}")
            item = json.loads(raw)
            if item["type"] == "error":
                raise RuntimeError(item["text"])
            if item["type"] == kind:
                return item

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


async def connect(host, port, username):
    peer = Connection(*await asyncio.open_connection(host, port))
    await peer.receive("info")
    await peer.send(type="hello", username=username)
    await peer.receive("welcome")
    return peer


async def run(host, port):
    suffix = str(int(datetime.now(timezone.utc).timestamp()))[-8:]
    alice_name, bob_name = "alice" + suffix, "bob" + suffix
    alice = await connect(host, port, alice_name)
    try:
        bob = await connect(host, port, bob_name)
        try:
            await alice.receive("presence")
            await alice.send(type="message", text="Hello from Alice")
            a1, b1 = await asyncio.gather(alice.receive("message"), bob.receive("message"))
            await bob.send(type="message", text="Hello from Bob")
            a2, b2 = await asyncio.gather(alice.receive("message"), bob.receive("message"))
            assert a1["text"] == b1["text"] == "Hello from Alice"
            assert a2["text"] == b2["text"] == "Hello from Bob"
            evidence = {
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                "host": host, "port": port,
                "simultaneous_users": [alice_name, bob_name],
                "alice_received": [a1, a2],
                "bob_received": [b1, b2],
            }
            Path("evidence").mkdir(exist_ok=True)
            Path("evidence/remote-demo.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence, indent=2))
        finally:
            await bob.close()
    finally:
        await alice.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port))
