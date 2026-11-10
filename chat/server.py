"""Connection lifecycle: framing, registration, dispatch, and cleanup."""

import json
import logging
import sqlite3

from chat.config import Settings
from chat.handlers import HANDLERS
from chat.handlers.rooms import send_history
from chat.peer import Peer
from chat.protocol import MAX_LINE, packet, valid_name
from chat.store import Store

log = logging.getLogger(__name__)

HELLO_HINT = 'Send {"type":"hello","username":"alice"} first'
NAME_RULE = "First message must be hello with a 2-20 character username (letters, digits, underscore)"


class ChatServer:
    def __init__(self, store=None, settings=None):
        settings = settings or Settings.from_env()
        self.peers = {}
        self.store = store or Store(":memory:")
        self.api_key = settings.api_key
        self.model = settings.model
        self.history_limit = settings.history_limit

    def broadcast(self, room, item, exclude=None):
        for peer in tuple(self.peers.values()):
            if peer.room == room and peer is not exclude:
                peer.send(item)

    async def close(self):
        await self.store.close()

    async def handle(self, reader, writer):
        peer = Peer(reader, writer)
        try:
            peer.send(packet("info", text=HELLO_HINT))
            while not reader.at_eof():
                msg = await self._read_frame(peer)
                if msg is False:
                    break
                if msg is None:
                    continue
                if peer.name is None:
                    await self._register(peer, msg)
                elif msg.get("type") == "quit":
                    break
                else:
                    await self._dispatch(peer, msg)
        except (ConnectionError, OSError):
            pass
        finally:
            await self._cleanup(peer, writer)

    async def _read_frame(self, peer):
        """Return a dict, None for a bad-but-recoverable frame, or False to disconnect."""
        try:
            raw = await peer.reader.readline()
        except ValueError:
            peer.send(packet("error", text=f"Frame exceeds {MAX_LINE} bytes"))
            return False
        if not raw:
            return False
        try:
            msg = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            peer.send(packet("error", text="Expected one UTF-8 JSON object per line"))
            return None
        if not isinstance(msg, dict):
            peer.send(packet("error", text="Expected a JSON object"))
            return None
        return msg

    async def _register(self, peer, msg):
        name = msg.get("username")
        if msg.get("type") != "hello" or not valid_name(name):
            peer.send(packet("error", text=NAME_RULE))
            return
        if name.lower() in self.peers:
            peer.send(packet("error", text="Username is already in use"))
            return
        peer.name = name
        self.peers[peer.key] = peer
        peer.send(packet("welcome", username=name, room=peer.room))
        self.broadcast(peer.room, packet("presence", username=name, action="joined"), exclude=peer)
        await self._guarded(peer, send_history(self, peer, peer.room))

    async def _dispatch(self, peer, msg):
        handler = HANDLERS.get(msg.get("type"))
        if handler is None:
            peer.send(packet("error", text="Unknown message type"))
            return
        await self._guarded(peer, handler(self, peer, msg))

    async def _guarded(self, peer, operation):
        """Run a handler; storage faults are logged and reported without leaking details."""
        try:
            await operation
        except sqlite3.Error:
            log.exception("Storage error while serving %s", peer.name)
            peer.send(packet("error", text="The server could not complete that request"))

    async def _cleanup(self, peer, writer):
        if peer.ai_task is not None:
            peer.ai_task.cancel()
        if peer.name and self.peers.get(peer.key) is peer:
            del self.peers[peer.key]
            self.broadcast(peer.room, packet("presence", username=peer.name, action="left"))
        peer.sender.cancel()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

