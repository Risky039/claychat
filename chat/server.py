"""Connection lifecycle: framing, registration, dispatch, timeouts, and cleanup."""

import asyncio
import json
import logging
import sqlite3

from chat.config import Settings
from chat.handlers import HANDLERS
from chat.handlers.rooms import send_history
from chat.peer import Peer
from chat.protocol import MAX_LINE, packet, valid_name
from chat.ratelimit import RateLimiter
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
        self.hello_timeout = settings.hello_timeout
        self.idle_timeout = settings.idle_timeout
        self.msg_limiter = RateLimiter(rate=settings.msg_rate, capacity=settings.msg_burst)

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
                timeout = self.hello_timeout if peer.name is None else self.idle_timeout
                msg = await self._read_frame(peer, timeout=timeout)
                if msg is False:
                    break
                if msg is None:
                    continue
                if peer.name is None:
                    await self._register(peer, msg)
                elif msg.get("type") == "ping":
                    peer.send(packet("pong"))
                elif msg.get("type") == "quit":
                    break
                else:
                    await self._dispatch(peer, msg)
        except (ConnectionError, OSError):
            pass
        finally:
            await self._cleanup(peer, writer)

    async def _read_frame(self, peer, timeout=None):
        """Return a dict, None for a bad-but-recoverable frame, or False to disconnect."""
        try:
            raw = await asyncio.wait_for(peer.reader.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            label = "Registration timeout" if peer.name is None else "Idle timeout"
            peer.send(packet("error", text=f"{label}: connection closed"))
            return False
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
        if msg.get("type") != "hello":
            peer.send(packet("error", text=NAME_RULE))
            return

        token = msg.get("token")
        if isinstance(token, str) and token.strip():
            user = await self.store.user_by_token(token.strip())
            if user is None:
                peer.send(packet("error", text="Invalid or expired session token"))
                return
            name = user["username"]
            if name.lower() in self.peers:
                peer.send(packet("error", text="Username is already in use"))
                return
            peer.name = name
            peer.user_id = user["id"]
            peer.authenticated = True
        else:
            name = msg.get("username")
            if not valid_name(name):
                peer.send(packet("error", text=NAME_RULE))
                return
            if await self.store.user_exists(name):
                peer.send(packet("error", text="Username is registered; sign in with your password"))
                return
            if name.lower() in self.peers:
                peer.send(packet("error", text="Username is already in use"))
                return
            peer.name = name
            peer.authenticated = False

        self.peers[peer.key] = peer
        peer.send(packet("welcome", username=peer.name, room=peer.room, authenticated=peer.authenticated))
        self.broadcast(peer.room, packet("presence", username=peer.name, action="joined"), exclude=peer)
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
        try:
            peer.outbox.put_nowait(None)
            await asyncio.wait_for(peer.sender, timeout=0.5)
        except (asyncio.QueueFull, asyncio.TimeoutError, asyncio.CancelledError):
            peer.sender.cancel()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
