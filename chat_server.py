"""Run the async TCP group chat (with optional Meta Model API assistant).

The implementation lives in the ``chat`` package; this module is the terminal
entry point and keeps the original import names working.
"""

import argparse
import asyncio
import logging

from chat.ai import ask_meta  # noqa: F401  (re-exported for compatibility)
from chat.config import Settings
from chat.protocol import MAX_LINE, packet  # noqa: F401
from chat.server import ChatServer
from chat.store import Store

__all__ = ["ChatServer", "MAX_LINE", "ask_meta", "packet", "main"]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    chat = ChatServer(store=Store(settings.db_path, database_url=settings.database_url), settings=settings)
    server = await asyncio.start_server(chat.handle, args.host, args.port, limit=MAX_LINE)
    history = "PostgreSQL" if settings.database_url else settings.db_path
    print(f"TCP chat listening on {args.host}:{args.port} (history: {history})", flush=True)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await chat.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
