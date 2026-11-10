"""Meta Model API client: private assistant ("Chunky"), SSE streaming, room @ai, and room summaries."""

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request

from chat.protocol import packet

log = logging.getLogger(__name__)

AI_NAME = "Chunky"
AI_HISTORY_MESSAGES = 12  # six completed turns
AI_COOLDOWN_SECONDS = 5
ROOM_CONTEXT_MESSAGES = 20
META_URL = "https://api.meta.ai/v1/chat/completions"
ROOM_MENTION_RE = re.compile(r"^\s*@(?:ai|chunky)\b[:,\s]*(.+)$", re.IGNORECASE | re.DOTALL)

AI_INSTRUCTIONS = (
    "You are Chunky, a helpful AI assistant in a chat application. Answer the user's question directly, "
    "use the conversation history when relevant, and keep replies clear and concise. "
    "Do not claim to have seen other users' chats or external facts you were not given."
)

ROOM_AI_INSTRUCTIONS = (
    "You are Chunky, a helpful AI participant in a shared group chat room. "
    "Use the provided recent room transcript for context and answer the user's request concisely."
)

SUMMARY_INSTRUCTIONS = (
    "You are Chunky. Summarize the provided chat room transcript into concise bullet points "
    "highlighting key topics, decisions, and open questions."
)


def extract_room_mention(text):
    if not isinstance(text, str):
        return None
    match = ROOM_MENTION_RE.match(text)
    if not match:
        return None
    prompt = match.group(1).strip()
    return prompt or None


def parse_sse_lines(lines):
    """Yield visible content deltas from OpenAI/Meta SSE byte or str lines."""
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
            delta = event["choices"][0].get("delta", {})
            content = delta.get("content")
            if isinstance(content, str) and content:
                yield content
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            continue


def ask_meta(messages, api_key, model):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "reasoning_effort": "minimal",
        "max_completion_tokens": 400,
    }).encode()
    request = urllib.request.Request(
        META_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=25) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Meta returned no visible answer")
    return content


def stream_meta(messages, api_key, model):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "reasoning_effort": "minimal",
        "max_completion_tokens": 400,
        "stream": True,
    }).encode()
    request = urllib.request.Request(
        META_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=25) as response:
        yield from parse_sse_lines(response)


def _http_error_text(code):
    if code == 401:
        return "The server's Meta API key was rejected"
    if code == 429:
        return f"{AI_NAME} is rate limited; try again later"
    return f"{AI_NAME} returned HTTP {code}"


async def reply(server, peer, prompt, request_id, generation, stream=False):
    """Ask Meta on a worker thread; deliver the answer only if the context wasn't reset meanwhile."""
    messages = [
        {"role": "developer", "content": AI_INSTRUCTIONS},
        *peer.ai_history[-AI_HISTORY_MESSAGES:],
        {"role": "user", "content": prompt},
    ]

    def current():
        return generation == peer.ai_generation and not peer.closing

    try:
        if stream:
            loop = asyncio.get_running_loop()

            def _consume_stream():
                parts = []
                for chunk in stream_meta(messages, server.api_key, server.model):
                    parts.append(chunk)
                    loop.call_soon_threadsafe(
                        lambda c=chunk: peer.send(packet("ai_delta", request_id=request_id, delta=c))
                        if current()
                        else None
                    )
                full = "".join(parts)
                if not full.strip():
                    raise ValueError("Meta returned no visible answer")
                return full

            answer = await asyncio.to_thread(_consume_stream)
        else:
            answer = await asyncio.to_thread(ask_meta, messages, server.api_key, server.model)

        if current():
            peer.ai_history = [
                *peer.ai_history,
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ][-AI_HISTORY_MESSAGES:]
            peer.send(
                packet(
                    "ai",
                    username=AI_NAME,
                    text=answer,
                    request_id=request_id,
                    turns=len(peer.ai_history) // 2,
                )
            )
    except urllib.error.HTTPError as exc:
        log.warning("Meta API HTTP %s for request %s", exc.code, request_id)
        if current():
            peer.send(packet("error", source="ai", request_id=request_id, text=_http_error_text(exc.code)))
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        log.warning("Meta API request %s failed: %s", request_id, type(exc).__name__)
        if current():
            peer.send(packet("error", source="ai", request_id=request_id, text=f"{AI_NAME} request failed: {type(exc).__name__}"))
    finally:
        if generation == peer.ai_generation:
            peer.ai_pending = False
            peer.ai_task = None


async def room_reply(server, peer, room, prompt):
    """Answer an @ai mention in ``room`` using recent room history and broadcast Chunky's message."""
    if not server.api_key:
        peer.send(packet("error", source="ai", text=f"{AI_NAME} is not configured on this server"))
        return
    history, _ = await server.store.room_history(room, limit=ROOM_CONTEXT_MESSAGES)
    transcript = "\n".join(f"{m['username']}: {m['text']}" for m in history if m.get("text"))
    messages = [
        {"role": "developer", "content": ROOM_AI_INSTRUCTIONS},
        {
            "role": "user",
            "content": f"Recent #{room} transcript:\n{transcript}\n\nQuestion from {peer.name}: {prompt}",
        },
    ]
    try:
        answer = await asyncio.to_thread(ask_meta, messages, server.api_key, server.model)
        saved = await server.store.add_room_message(room, AI_NAME, answer.strip())
        server.broadcast(room, packet("message", **saved))
    except urllib.error.HTTPError as exc:
        peer.send(packet("error", source="ai", text=_http_error_text(exc.code)))
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        peer.send(packet("error", source="ai", text=f"{AI_NAME} request failed: {type(exc).__name__}"))


async def summarize_room(server, peer, room, count, request_id):
    """Summarize the last ``count`` messages in ``room`` privately for ``peer``."""
    try:
        history, _ = await server.store.room_history(room, limit=count)
        if not history:
            peer.send(
                packet(
                    "ai",
                    kind="summary",
                    room=room,
                    username=AI_NAME,
                    text=f"No messages in #{room} yet to summarize.",
                    request_id=request_id,
                )
            )
            return
        transcript = "\n".join(f"{m['username']}: {m['text']}" for m in history if m.get("text"))
        messages = [
            {"role": "developer", "content": SUMMARY_INSTRUCTIONS},
            {"role": "user", "content": f"Summarize these {len(history)} messages from #{room}:\n\n{transcript}"},
        ]
        answer = await asyncio.to_thread(ask_meta, messages, server.api_key, server.model)
        if not peer.closing:
            peer.send(
                packet(
                    "ai",
                    kind="summary",
                    room=room,
                    username=AI_NAME,
                    text=answer.strip(),
                    request_id=request_id,
                )
            )
    except urllib.error.HTTPError as exc:
        if not peer.closing:
            peer.send(packet("error", source="ai", request_id=request_id, text=_http_error_text(exc.code)))
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        if not peer.closing:
            peer.send(packet("error", source="ai", request_id=request_id, text=f"{AI_NAME} request failed: {type(exc).__name__}"))
    finally:
        peer.ai_pending = False
        peer.ai_task = None
