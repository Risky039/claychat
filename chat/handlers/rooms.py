"""Room features: messages, joining, member lists, and stored history."""

from chat.protocol import ROOM_RULE, packet, valid_message_id, valid_room, valid_text


async def send_history(server, peer, room, before=None):
    messages, has_more = await server.store.room_history(room, limit=server.history_limit, before=before)
    fields = {"room": room, "messages": messages, "has_more": has_more}
    if before is not None:
        fields["before"] = before
    peer.send(packet("history", **fields))


async def on_message(server, peer, msg):
    text = msg.get("text")
    if not valid_text(text):
        peer.send(packet("error", text="Message must contain 1-2000 characters"))
        return
    if not server.msg_limiter.allow(peer.key):
        peer.send(packet("error", text="Slow down: you are sending messages too quickly"))
        return
    saved = await server.store.add_room_message(peer.room, peer.name, text.strip())
    server.broadcast(peer.room, packet("message", **saved))


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
