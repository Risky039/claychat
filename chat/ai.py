"""Meta Model API client and the private, per-connection assistant ("Chunky")."""

import asyncio
import json
import logging
import urllib.error
import urllib.request

from chat.protocol import packet

log = logging.getLogger(__name__)

AI_NAME = "Chunky"
AI_HISTORY_MESSAGES = 12  # six completed turns
AI_COOLDOWN_SECONDS = 5
META_URL = "https://api.meta.ai/v1/chat/completions"
AI_INSTRUCTIONS = (
    "You are Chunky, a helpful AI assistant in a chat application. Answer the user's question directly, "
    "use the conversation history when relevant, and keep replies clear and concise. "
    "Do not claim to have seen other users' chats or external facts you were not given."
)


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
    # Use direct HTTPS so a broken inherited proxy cannot block the AI feature.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=25) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Meta returned no visible answer")
    return content


def _http_error_text(code):
    if code == 401:
        return "The server's Meta API key was rejected"
    if code == 429:
        return f"{AI_NAME} is rate limited; try again later"
    return f"{AI_NAME} returned HTTP {code}"


async def reply(server, peer, prompt, request_id, generation):
    """Ask Meta on a worker thread; deliver the answer only if the context wasn't reset meanwhile."""
    messages = [
        {"role": "developer", "content": AI_INSTRUCTIONS},
        *peer.ai_history[-AI_HISTORY_MESSAGES:],
        {"role": "user", "content": prompt},
    ]

    def current():
        return generation == peer.ai_generation and not peer.closing

    try:
        answer = await asyncio.to_thread(ask_meta, messages, server.api_key, server.model)
        if current():
            peer.ai_history = [
                *peer.ai_history,
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ][-AI_HISTORY_MESSAGES:]
            peer.send(packet("ai", username=AI_NAME, text=answer, request_id=request_id, turns=len(peer.ai_history) // 2))
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

