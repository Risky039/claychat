"""One connected client: its socket, identity, room, outgoing queue, and AI state."""

import asyncio

from chat.protocol import DEFAULT_ROOM, encode

OUTBOX_SIZE = 128


class Peer:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.name = None
        self.user_id = None
        self.authenticated = False
        self.room = DEFAULT_ROOM
        self.outbox = asyncio.Queue(maxsize=OUTBOX_SIZE)
        self.sender = asyncio.create_task(self.write_loop())
        self.last_ai = 0.0
        self.ai_history = []
        self.ai_pending = False
        self.ai_generation = 0
        self.ai_task = None

    @property
    def key(self):
        return self.name.lower() if self.name else None

    async def write_loop(self):
        try:
            while True:
                item = await self.outbox.get()
                if item is None:
                    break
                self.writer.write(encode(item))
                await self.writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.writer.close()

    def send(self, item):
        """Queue a frame; a client that falls 128 frames behind is disconnected."""
        try:
            self.outbox.put_nowait(item)
        except asyncio.QueueFull:
            self.writer.close()

    @property
    def closing(self):
        return self.writer.is_closing()
