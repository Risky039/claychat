"""Serve the browser UI, HTTP auth API, and bridge each WebSocket to the raw TCP chat server."""

import argparse
import asyncio
import hmac
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from chat.auth import valid_password
from chat.config import Settings
from chat.protocol import MAX_LINE, valid_name
from chat.ratelimit import RateLimiter
from chat.server import ChatServer
from chat.store import Store
from chat.uploads import (
    MAX_UPLOAD_BYTES,
    clean_filename,
    detect_mime,
    new_attachment_id,
    valid_attachment_id,
)

DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
SESSION_COOKIE = "claychat_session"
SESSION_MAX_AGE = 30 * 86400


def _same_origin(request):
    origin = request.headers.get("Origin")
    if not origin:
        return True
    origin_host = urlsplit(origin).netloc.lower()
    allowed = {request.host.lower()}
    forwarded = request.headers.get("X-Forwarded-Host", "")
    for part in forwarded.split(","):
        if part.strip():
            allowed.add(part.strip().lower())
    return origin_host in allowed


def _extract_token(request):
    cookie = request.cookies.get(SESSION_COOKIE, "").strip()
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _client_ip(request):

    peername = request.transport.get_extra_info("peername") if request.transport else None
    return peername[0] if peername else "unknown"


def _set_session_cookie(response, request, token):
    secure = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )


def create_web_app(tcp_host="127.0.0.1", tcp_port=8765, store=None, settings=None):
    settings = settings or Settings.from_env()
    owns_store = store is None
    store = store or Store(settings.db_path, database_url=settings.database_url)
    upload_dir = Path(settings.upload_dir).resolve()
    auth_limiter = RateLimiter(rate=0.2, capacity=8.0)
    upload_limiter = RateLimiter(rate=0.2, capacity=5.0)
    app = web.Application(client_max_size=MAX_UPLOAD_BYTES + 65536)

    if owns_store:
        async def _close_store(_app):
            await store.close()

        app.on_cleanup.append(_close_store)

    async def _read_json(request):
        if not _same_origin(request):
            raise web.HTTPForbidden(text="Cross-origin requests are not allowed")
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="Expected a JSON request body") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Expected a JSON object")
        return body

    async def register(request):
        body = await _read_json(request)
        if not auth_limiter.allow(_client_ip(request)):
            return web.json_response({"error": "Too many attempts; try again shortly"}, status=429)
        if settings.invite_code:
            provided = body.get("invite_code", "")
            if not isinstance(provided, str) or not hmac.compare_digest(provided.strip(), settings.invite_code):
                return web.json_response({"error": "A valid invite code is required to register"}, status=403)
        username = body.get("username", "")
        password = body.get("password", "")
        if not valid_name(username):
            return web.json_response(
                {"error": "Username must be 2-20 letters, digits, or underscores, starting with a letter"},
                status=400,
            )
        if not valid_password(password):
            return web.json_response({"error": "Password must be 8-128 characters"}, status=400)
        try:
            user = await store.create_user(username, password)
        except ValueError:
            return web.json_response({"error": "Username is already registered"}, status=409)
        token = await store.create_session(user["id"])
        response = web.json_response(
            {"username": user["username"], "authenticated": True, "token": token},
            status=201,
        )
        _set_session_cookie(response, request, token)
        return response

    async def login(request):
        body = await _read_json(request)
        if not auth_limiter.allow(_client_ip(request)):
            return web.json_response({"error": "Too many attempts; try again shortly"}, status=429)
        username = body.get("username", "")
        password = body.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            return web.json_response({"error": "Invalid username or password"}, status=401)
        user = await store.authenticate_user(username.strip(), password)
        if user is None:
            return web.json_response({"error": "Invalid username or password"}, status=401)
        token = await store.create_session(user["id"])
        response = web.json_response(
            {"username": user["username"], "authenticated": True, "token": token},
            status=200,
        )
        _set_session_cookie(response, request, token)
        return response

    async def logout(request):
        if not _same_origin(request):
            raise web.HTTPForbidden(text="Cross-origin requests are not allowed")
        token = _extract_token(request)
        if token:
            await store.revoke_session(token)
        response = web.json_response({"authenticated": False})
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def me(request):
        token = _extract_token(request)
        user = await store.user_by_token(token) if token else None
        if user is None:
            return web.json_response(
                {"authenticated": False, "invite_required": bool(settings.invite_code)}
            )
        return web.json_response(
            {
                "authenticated": True,
                "username": user["username"],
                "invite_required": bool(settings.invite_code),
            }
        )

    async def upload_file(request):
        if not _same_origin(request):
            raise web.HTTPForbidden(text="Cross-origin requests are not allowed")
        if not upload_limiter.allow(_client_ip(request)):
            return web.json_response({"error": "Upload rate limit reached; try again shortly"}, status=429)
        filename = "attachment"
        data = b""
        if request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            part = await reader.next()
            if part is None:
                return web.json_response({"error": "Missing file part"}, status=400)
            filename = clean_filename(part.filename or "attachment")
            chunks = []
            total = 0
            while True:
                chunk = await part.read_chunk(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    return web.json_response({"error": "File exceeds 5 MB limit"}, status=413)
                chunks.append(chunk)
            data = b"".join(chunks)
        else:
            filename = clean_filename(request.headers.get("X-Filename", "attachment"))
            data = await request.read()
        try:
            mime = detect_mime(data, filename)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        token = _extract_token(request)
        user = await store.user_by_token(token) if token else None
        uploader = user["username"] if user else "guest"
        att_id = new_attachment_id()

        def _write_disk():
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / att_id).write_bytes(data)

        await asyncio.to_thread(_write_disk)
        meta = await store.create_attachment(att_id, uploader, filename, mime, len(data))
        return web.json_response(meta, status=201)

    async def download_file(request):
        att_id = request.match_info.get("id", "")
        if not valid_attachment_id(att_id):
            raise web.HTTPNotFound()
        meta = await store.get_attachment(att_id)
        target = (upload_dir / att_id).resolve()
        if meta is None or not target.is_relative_to(upload_dir) or not target.is_file():
            raise web.HTTPNotFound()
        disposition = "inline" if meta["mime"].startswith("image/") else "attachment"
        response = web.FileResponse(target)
        response.headers["Content-Type"] = meta["mime"]
        response.headers["Content-Disposition"] = f'{disposition}; filename="{clean_filename(meta["name"])}"'
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
        return response

    async def asset(request):
        name = request.match_info.get("path", "index.html")
        target = (DIST_DIR / name).resolve()
        if not target.is_relative_to(DIST_DIR.resolve()) or not target.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(target)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; "
            "font-src 'self'; base-uri 'none'; form-action 'self'"
        )
        return response

    async def health(request):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(tcp_host, tcp_port), 2)
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            return web.json_response({"status": "unavailable"}, status=503)
        return web.json_response({"status": "ok", "tcp_port": tcp_port})

    async def ready(request):
        try:
            await store.user_exists("__readyz__")
            reader, writer = await asyncio.wait_for(asyncio.open_connection(tcp_host, tcp_port), 2)
            writer.close()
            await writer.wait_closed()
        except Exception:
            return web.json_response({"status": "not_ready"}, status=503)
        return web.json_response({"status": "ready", "tcp_port": tcp_port})

    async def websocket(request):
        if not _same_origin(request):
            raise web.HTTPForbidden(text="Cross-origin WebSocket connections are not allowed")
        cookie_token = _extract_token(request)
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(tcp_host, tcp_port), 3)
        except (OSError, asyncio.TimeoutError):
            raise web.HTTPServiceUnavailable(text="TCP chat server is unavailable")
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=MAX_LINE)
        try:
            await ws.prepare(request)
        except Exception:
            writer.close()
            await writer.wait_closed()
            raise

        async def tcp_to_browser():
            try:
                while not ws.closed:
                    line = await reader.readline()
                    if not line:
                        break
                    await ws.send_str(line.decode("utf-8").rstrip("\r\n"))
            except (OSError, UnicodeDecodeError, ValueError, ConnectionError):
                pass
            finally:
                if not ws.closed:
                    await ws.close()

        forward = asyncio.create_task(tcp_to_browser())
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        item = json.loads(message.data)
                        if not isinstance(item, dict):
                            raise ValueError("Expected JSON object")
                    except (json.JSONDecodeError, ValueError):
                        await ws.send_json({"type": "error", "text": "Expected a JSON object"})
                        continue
                    if item.get("type") == "hello" and not item.get("token") and cookie_token:
                        item = {**item, "token": cookie_token}
                    writer.write((json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()
                elif message.type == WSMsgType.BINARY:
                    await ws.send_json({"type": "error", "text": "Binary frames are not supported"})
                elif message.type == WSMsgType.ERROR:
                    break
        except (OSError, ConnectionError):
            pass
        finally:
            forward.cancel()
            try:
                await forward
            except asyncio.CancelledError:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass
            if not ws.closed:
                await ws.close()
        return ws

    app.router.add_post("/api/register", register)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/uploads", upload_file)
    app.router.add_get("/api/uploads/{id}", download_file)
    app.router.add_get("/", asset)
    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", ready)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/{path:.*}", asset)
    return app


async def main():
    parser = argparse.ArgumentParser(description="Run the raw TCP chat and claymorphism web interface")
    parser.add_argument("--tcp-host", default="127.0.0.1")
    parser.add_argument("--tcp-port", type=int, default=8765)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=int(os.getenv("PORT", "8080")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings.from_env()
    store = Store(settings.db_path, database_url=settings.database_url)
    chat = ChatServer(store=store, settings=settings)
    tcp = await asyncio.start_server(chat.handle, args.tcp_host, args.tcp_port, limit=MAX_LINE)
    gateway_host = "127.0.0.1" if args.tcp_host in {"0.0.0.0", "::"} else args.tcp_host
    runner = web.AppRunner(create_web_app(gateway_host, args.tcp_port, store=store, settings=settings))
    try:
        if settings.database_url:
            await store.user_exists("__readyz__")
        await runner.setup()
        site = web.TCPSite(runner, args.web_host, args.web_port)
        await site.start()
        print(f"TCP chat: {args.tcp_host}:{args.tcp_port}", flush=True)
        print(f"Web interface: http://{args.web_host}:{args.web_port}", flush=True)
        print(f"Message history: {'PostgreSQL' if settings.database_url else settings.db_path}", flush=True)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        tcp.close()
        await tcp.wait_closed()
        await chat.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
