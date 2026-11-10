"""Serve the browser UI and bridge each WebSocket to the raw TCP chat server."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from chat.config import Settings
from chat.protocol import MAX_LINE
from chat.server import ChatServer
from chat.store import Store


DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"


def create_web_app(tcp_host="127.0.0.1", tcp_port=8765):
    app = web.Application(client_max_size=MAX_LINE)

    async def asset(request):
        name = request.match_info.get("path", "index.html")
        target = (DIST_DIR / name).resolve()
        if not target.is_relative_to(DIST_DIR.resolve()) or not target.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(target)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; "
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

    async def websocket(request):
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != request.host.lower():
            raise web.HTTPForbidden(text="Cross-origin WebSocket connections are not allowed")
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

    app.router.add_get("/", asset)
    app.router.add_get("/healthz", health)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/{path:.*}", asset)
    return app


async def main():
    parser = argparse.ArgumentParser(description="Run the raw TCP chat and claymorphism web interface")
    parser.add_argument("--tcp-host", default="127.0.0.1")
    parser.add_argument("--tcp-port", type=int, default=8765)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings.from_env()
    chat = ChatServer(store=Store(settings.db_path), settings=settings)
    tcp = await asyncio.start_server(chat.handle, args.tcp_host, args.tcp_port, limit=MAX_LINE)
    gateway_host = "127.0.0.1" if args.tcp_host in {"0.0.0.0", "::"} else args.tcp_host
    runner = web.AppRunner(create_web_app(gateway_host, args.tcp_port))
    try:
        await runner.setup()
        site = web.TCPSite(runner, args.web_host, args.web_port)
        await site.start()
        print(f"TCP chat: {args.tcp_host}:{args.tcp_port}", flush=True)
        print(f"Web interface: http://{args.web_host}:{args.web_port}", flush=True)
        print(f"Message history: {settings.db_path}", flush=True)
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
