"""Private AI assistant commands: ask (with optional streaming), summarize room, show history, reset."""

import asyncio
import uuid

from chat import ai
from chat.protocol import ROOM_RULE, packet, valid_room, valid_text


async def on_ai(server, peer, msg):
    prompt = msg.get("text")
    stream = bool(msg.get("stream"))
    now = asyncio.get_running_loop().time()
    if not valid_text(prompt):
        peer.send(packet("error", source="ai", text="AI prompt must contain 1-2000 characters"))
    elif not server.api_key:
        peer.send(packet("error", source="ai", text=f"{ai.AI_NAME} is not configured on this server"))
    elif peer.ai_pending:
        peer.send(packet("error", source="ai", text=f"{ai.AI_NAME} is still answering your previous message"))
    elif now - peer.last_ai < ai.AI_COOLDOWN_SECONDS:
        peer.send(packet("error", source="ai", text="Wait five seconds between AI requests"))
    else:
        peer.last_ai = now
        peer.ai_pending = True
        request_id = uuid.uuid4().hex[:12]
        peer.send(packet("ai_status", state="thinking", request_id=request_id))
        peer.ai_task = asyncio.create_task(
            ai.reply(server, peer, prompt.strip(), request_id, peer.ai_generation, stream=stream)
        )


async def on_summarize(server, peer, msg):
    room = msg.get("room", peer.room)
    raw_count = msg.get("count", 30)
    if not valid_room(room):
        peer.send(packet("error", source="ai", text=ROOM_RULE))
        return
    if not isinstance(raw_count, int) or isinstance(raw_count, bool) or not (1 <= raw_count <= 100):
        peer.send(packet("error", source="ai", text="Summary count must be between 1 and 100"))
        return
    if not server.api_key:
        peer.send(packet("error", source="ai", text=f"{ai.AI_NAME} is not configured on this server"))
        return
    if peer.ai_pending:
        peer.send(packet("error", source="ai", text=f"{ai.AI_NAME} is still answering your previous message"))
        return
    peer.ai_pending = True
    request_id = uuid.uuid4().hex[:12]
    peer.send(packet("ai_status", state="thinking", request_id=request_id))
    peer.ai_task = asyncio.create_task(ai.summarize_room(server, peer, room, raw_count, request_id))


async def on_ai_history(server, peer, msg):
    peer.send(packet("ai_history", messages=list(peer.ai_history), turns=len(peer.ai_history) // 2))


async def on_ai_reset(server, peer, msg):
    peer.ai_generation += 1
    if peer.ai_task is not None:
        peer.ai_task.cancel()
    peer.ai_task = None
    peer.ai_pending = False
    peer.ai_history = []
    peer.last_ai = 0.0
    peer.send(packet("ai_reset", text="AI conversation cleared"))
