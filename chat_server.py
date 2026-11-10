"""Async TCP group chat with an optional Meta Model API assistant."""

import argparse
import asyncio
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,19}$")
ROOM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,29}$")
MAX_LINE = 8192
MAX_TEXT = 2000
AI_HISTORY_MESSAGES = 12
AI_INSTRUCTIONS = (
    "You are Chunky, a helpful AI assistant in a chat application. Answer the user's question directly, "
    "use the conversation history when relevant, and keep replies clear and concise. "
    "Do not claim to have seen other users' chats or external facts you were not given."
)


def packet(kind, **fields):
    return {"type": kind, "time": datetime.now(timezone.utc).isoformat(), **fields}


class Peer:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.name = None
        self.room = "lobby"
        self.outbox = asyncio.Queue(maxsize=128)
        self.sender = asyncio.create_task(self.write_loop())
        self.last_ai = 0.0
        self.ai_history = []
        self.ai_pending = False
        self.ai_generation = 0
        self.ai_task = None

    async def write_loop(self):
        try:
            while True:
                item = await self.outbox.get()
                self.writer.write((json.dumps(item, ensure_ascii=False) + "\n").encode())
                await self.writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.writer.close()

    def send(self, item):
        try:
            self.outbox.put_nowait(item)
        except asyncio.QueueFull:
            self.writer.close()


def ask_meta(messages, api_key, model):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "reasoning_effort": "minimal",
        "max_completion_tokens": 400,
    }).encode()
    request = urllib.request.Request(
        "https://api.meta.ai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    # Use direct HTTPS so a broken inherited proxy cannot block the AI feature.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=25) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Meta returned no visible answer")
    return content


class ChatServer:
    def __init__(self):
        self.peers = {}
        self.api_key = os.getenv("MODEL_API_KEY", "")
        if not self.api_key:
            key_file = Path(__file__).resolve().parent / "deployment-private" / "meta_model_api_key"
            if key_file.is_file():
                self.api_key = key_file.read_text(encoding="utf-8").strip()
        self.model = os.getenv("META_MODEL", "muse-spark-1.3")

    def broadcast(self, room, item, exclude=None):
        for peer in tuple(self.peers.values()):
            if peer.room == room and peer is not exclude:
                peer.send(item)

    async def handle(self, reader, writer):
        peer = Peer(reader, writer)
        try:
            peer.send(packet("info", text="Send {\"type\":\"hello\",\"username\":\"alice\"} first"))
            while not reader.at_eof():
                try:
                    raw = await reader.readline()
                except ValueError:
                    peer.send(packet("error", text="Frame exceeds 8192 bytes"))
                    break
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    peer.send(packet("error", text="Expected one UTF-8 JSON object per line"))
                    continue
                if not isinstance(msg, dict):
                    peer.send(packet("error", text="Expected a JSON object"))
                    continue
                if peer.name is None:
                    name = msg.get("username")
                    if msg.get("type") != "hello" or not isinstance(name, str) or not NAME_RE.fullmatch(name):
                        peer.send(packet("error", text="First message must be hello with a 2-20 character username (letters, digits, underscore)"))
                        continue
                    if name.lower() in self.peers:
                        peer.send(packet("error", text="Username is already in use"))
                        continue
                    peer.name = name
                    self.peers[name.lower()] = peer
                    peer.send(packet("welcome", username=name, room=peer.room))
                    self.broadcast(peer.room, packet("presence", username=name, action="joined"), peer)
                    continue
                kind = msg.get("type")
                if kind == "message":
                    value = msg.get("text")
                    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
                        peer.send(packet("error", text="Message must contain 1-2000 characters"))
                    else:
                        self.broadcast(peer.room, packet("message", room=peer.room, username=peer.name, text=value.strip()))
                elif kind == "dm":
                    target = msg.get("to")
                    value = msg.get("text")
                    if not isinstance(target, str) or not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
                        peer.send(packet("error", text="DM needs a recipient and 1-2000 characters"))
                    elif target.lower() not in self.peers:
                        peer.send(packet("error", text="Recipient is offline"))
                    else:
                        recipient = self.peers[target.lower()]
                        item = packet("dm", username=peer.name, to=recipient.name, text=value.strip())
                        recipient.send(item)
                        if recipient is not peer:
                            peer.send(item)
                elif kind == "join":
                    room = msg.get("room")
                    if not isinstance(room, str) or not ROOM_RE.fullmatch(room):
                        peer.send(packet("error", text="Room must be 1-30 letters, digits, underscore or hyphen, starting with a letter"))
                    elif room != peer.room:
                        previous = peer.room
                        self.broadcast(previous, packet("presence", username=peer.name, action="left"), peer)
                        peer.room = room
                        peer.send(packet("joined", room=room))
                        self.broadcast(room, packet("presence", username=peer.name, action="joined"), peer)
                elif kind == "users":
                    peer.send(packet("users", room=peer.room, usernames=sorted(p.name for p in self.peers.values() if p.room == peer.room)))
                elif kind == "ai":
                    prompt = msg.get("text")
                    now = asyncio.get_running_loop().time()
                    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_TEXT:
                        peer.send(packet("error", source="ai", text="AI prompt must contain 1-2000 characters"))
                    elif not self.api_key:
                        peer.send(packet("error", source="ai", text="Chunky is not configured on this server"))
                    elif peer.ai_pending:
                        peer.send(packet("error", source="ai", text="Chunky is still answering your previous message"))
                    elif now - peer.last_ai < 5:
                        peer.send(packet("error", source="ai", text="Wait five seconds between AI requests"))
                    else:
                        peer.last_ai = now
                        peer.ai_pending = True
                        request_id = uuid.uuid4().hex[:12]
                        peer.send(packet("ai_status", state="thinking", request_id=request_id))
                        peer.ai_task = asyncio.create_task(self.ai_reply(peer, prompt.strip(), request_id, peer.ai_generation))
                elif kind == "ai_history":
                    peer.send(packet("ai_history", messages=list(peer.ai_history), turns=len(peer.ai_history) // 2))
                elif kind == "ai_reset":
                    peer.ai_generation += 1
                    if peer.ai_task is not None:
                        peer.ai_task.cancel()
                    peer.ai_task = None
                    peer.ai_pending = False
                    peer.ai_history.clear()
                    peer.last_ai = 0.0
                    peer.send(packet("ai_reset", text="AI conversation cleared"))
                elif kind == "quit":
                    break
                else:
                    peer.send(packet("error", text="Unknown message type"))
        except (ConnectionError, OSError):
            pass
        finally:
            if peer.ai_task is not None:
                peer.ai_task.cancel()
            if peer.name and self.peers.get(peer.name.lower()) is peer:
                del self.peers[peer.name.lower()]
                self.broadcast(peer.room, packet("presence", username=peer.name, action="left"))
            peer.sender.cancel()
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def ai_reply(self, peer, prompt, request_id, generation):
        messages = [
            {"role": "developer", "content": AI_INSTRUCTIONS},
            *peer.ai_history[-AI_HISTORY_MESSAGES:],
            {"role": "user", "content": prompt},
        ]
        try:
            answer = await asyncio.to_thread(ask_meta, messages, self.api_key, self.model)
            if generation == peer.ai_generation and not peer.writer.is_closing():
                peer.ai_history.extend([
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ])
                del peer.ai_history[:-AI_HISTORY_MESSAGES]
                peer.send(packet("ai", username="Chunky", text=answer, request_id=request_id, turns=len(peer.ai_history) // 2))
        except urllib.error.HTTPError as exc:
            if generation == peer.ai_generation and not peer.writer.is_closing():
                if exc.code == 401:
                    detail = "The server's Meta API key was rejected"
                elif exc.code == 429:
                    detail = "Chunky is rate limited; try again later"
                else:
                    detail = f"Chunky returned HTTP {exc.code}"
                peer.send(packet("error", source="ai", request_id=request_id, text=detail))
        except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            if generation == peer.ai_generation and not peer.writer.is_closing():
                peer.send(packet("error", source="ai", request_id=request_id, text=f"Chunky request failed: {type(exc).__name__}"))
        finally:
            if generation == peer.ai_generation:
                peer.ai_pending = False
                peer.ai_task = None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    chat = ChatServer()
    server = await asyncio.start_server(chat.handle, args.host, args.port, limit=MAX_LINE)
    print(f"TCP chat listening on {args.host}:{args.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
