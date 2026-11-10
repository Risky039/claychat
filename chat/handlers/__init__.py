"""Maps each client request type to its handler: ``async def handler(server, peer, msg)``."""

from chat.handlers import assistant, direct, rooms

HANDLERS = {
    "message": rooms.on_message,
    "join": rooms.on_join,
    "users": rooms.on_users,
    "history": rooms.on_history,
    "dm": direct.on_dm,
    "ai": assistant.on_ai,
    "ai_history": assistant.on_ai_history,
    "ai_reset": assistant.on_ai_reset,
}

