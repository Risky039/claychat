"""Direct messages between two users and authenticated DM history."""

from chat.protocol import packet, valid_message_id, valid_name, valid_text


async def on_dm(server, peer, msg):
    target = msg.get("to")
    text = msg.get("text")
    if not isinstance(target, str) or not valid_text(text):
        peer.send(packet("error", text="DM needs a recipient and 1-2000 characters"))
        return
    if not server.msg_limiter.allow(peer.key):
        peer.send(packet("error", text="Slow down: you are sending messages too quickly"))
        return
    recipient = server.peers.get(target.lower())
    if recipient is None:
        peer.send(packet("error", text="Recipient is offline"))
        return
    saved = await server.store.add_dm(peer.name, recipient.name, text.strip())
    item = packet("dm", **saved)
    recipient.send(item)
    if recipient is not peer:
        peer.send(item)


async def on_dm_history(server, peer, msg):
    if not peer.authenticated:
        peer.send(packet("error", text="Sign in to view saved direct message history"))
        return
    other = msg.get("with_user")
    before = msg.get("before")
    if not valid_name(other):
        peer.send(packet("error", text="Invalid username for DM history"))
        return
    if before is not None and not valid_message_id(before):
        peer.send(packet("error", text="History 'before' must be a positive message id"))
        return
    messages, has_more = await server.store.dm_history(
        peer.name, other, limit=server.history_limit, before=before
    )
    fields = {"with_user": other, "messages": messages, "has_more": has_more}
    if before is not None:
        fields["before"] = before
    peer.send(packet("dm_history", **fields))
