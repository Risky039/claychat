"""Room features: messages, joining, member lists, stored history, typing, edits, deletes, reactions, and read receipts."""

import asyncio

from chat import ai
from chat.protocol import (
    MAX_TEXT,
    ROOM_RULE,
    packet,
    valid_emoji,
    valid_message_id,
    valid_room,
    valid_text,
)
from chat.uploads import valid_attachment_id


async def send_history(server, peer, room, before=None):
    messages, has_more = await server.store.room_history(room, limit=server.history_limit, before=before)
    fields = {"room": room, "messages": messages, "has_more": has_more}
    if before is not None:
        fields["before"] = before
    peer.send(packet("history", **fields))


async def on_message(server, peer, msg):
    text = msg.get("text", "")
    attachment_id = msg.get("attachment_id")
    if attachment_id is not None and not valid_attachment_id(attachment_id):
        peer.send(packet("error", text="Invalid attachment id"))
        return
    if attachment_id is None and not valid_text(text):
        peer.send(packet("error", text="Message must contain 1-2000 characters"))
        return
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        peer.send(packet("error", text="Message must contain 1-2000 characters"))
        return
    if not server.msg_limiter.allow(peer.key):
        peer.send(packet("error", text="Slow down: you are sending messages too quickly"))
        return
    try:
        saved = await server.store.add_room_message(
            peer.room, peer.name, text.strip(), attachment_id=attachment_id
        )
    except ValueError:
        peer.send(packet("error", text="Attachment not found"))
        return
    server.broadcast(peer.room, packet("message", **saved))
    mention_prompt = ai.extract_room_mention(text)
    if mention_prompt:
        asyncio.create_task(ai.room_reply(server, peer, peer.room, mention_prompt))


async def on_join(server, peer, msg):
    room = msg.get("room")
    if not valid_room(room):
        peer.send(packet("error", text=ROOM_RULE))
        return
    if room == peer.room:
        return
    server.broadcast(peer.room, packet("presence", username=peer.name, action="left"), exclude=peer)
    peer.room = room
    peer.send(packet("joined", room=room))
    server.broadcast(room, packet("presence", username=peer.name, action="joined"), exclude=peer)
    await send_history(server, peer, room)


async def on_users(server, peer, msg):
    names = sorted(p.name for p in server.peers.values() if p.room == peer.room)
    peer.send(packet("users", room=peer.room, usernames=names))


async def on_history(server, peer, msg):
    room = msg.get("room", peer.room)
    before = msg.get("before")
    if not valid_room(room):
        peer.send(packet("error", text=ROOM_RULE))
    elif before is not None and not valid_message_id(before):
        peer.send(packet("error", text="History 'before' must be a positive message id"))
    else:
        await send_history(server, peer, room, before)


async def on_typing(server, peer, msg):
    if not server.typing_limiter.allow(peer.key):
        return
    target = msg.get("to")
    if isinstance(target, str) and target.strip():
        recipient = server.peers.get(target.strip().lower())
        if recipient is not None and recipient is not peer:
            recipient.send(packet("typing", username=peer.name, to=recipient.name))
        return
    server.broadcast(peer.room, packet("typing", room=peer.room, username=peer.name), exclude=peer)


def _route_update(server, info, event):
    if "room" in info:
        server.broadcast(info["room"], event)
    else:
        for username in {info.get("username", ""), info.get("to", ""), info.get("author", "")}:
            if username:
                target = server.peers.get(username.lower())
                if target is not None:
                    target.send(event)


async def on_edit(server, peer, msg):
    msg_id = msg.get("id")
    text = msg.get("text")
    if not valid_message_id(msg_id) or not valid_text(text):
        peer.send(packet("error", text="Edit requires a valid message id and 1-2000 characters"))
        return
    try:
        updated = await server.store.edit_message(msg_id, peer.name, text.strip())
    except LookupError:
        peer.send(packet("error", text="Message not found"))
        return
    except PermissionError as exc:
        peer.send(packet("error", text=str(exc)))
        return
    _route_update(server, updated, packet("message_updated", **updated))


async def on_delete(server, peer, msg):
    msg_id = msg.get("id")
    if not valid_message_id(msg_id):
        peer.send(packet("error", text="Delete requires a valid message id"))
        return
    try:
        deleted = await server.store.delete_message(msg_id, peer.name)
    except LookupError:
        peer.send(packet("error", text="Message not found"))
        return
    except PermissionError as exc:
        peer.send(packet("error", text=str(exc)))
        return
    _route_update(server, deleted, packet("message_deleted", **deleted))


async def on_react(server, peer, msg):
    msg_id = msg.get("id")
    emoji = msg.get("emoji")
    if not valid_message_id(msg_id) or not valid_emoji(emoji):
        peer.send(packet("error", text="Unsupported emoji or invalid message id"))
        return
    try:
        updated = await server.store.toggle_reaction(msg_id, peer.name, emoji)
    except LookupError:
        peer.send(packet("error", text="Message not found"))
        return
    _route_update(server, updated, packet("reactions_updated", **updated))


async def on_read(server, peer, msg):
    msg_id = msg.get("id")
    if not valid_message_id(msg_id):
        peer.send(packet("error", text="Read receipt requires a valid message id"))
        return
    try:
        receipt = await server.store.mark_read(msg_id, peer.name)
    except LookupError:
        peer.send(packet("error", text="Message not found"))
        return
    if "room" in receipt:
        server.broadcast(receipt["room"], packet("read_receipt", **receipt), exclude=peer)
    else:
        for uname in {receipt.get("author", ""), receipt.get("to", "")}:
            if uname and uname.lower() != peer.key:
                other = server.peers.get(uname.lower())
                if other is not None:
                    other.send(packet("read_receipt", id=receipt["id"], username=peer.name, to=other.name))
