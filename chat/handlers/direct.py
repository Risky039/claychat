"""Direct messages between two connected users.

DMs are stored (for future account-scoped history), but their history is not
served yet: without authenticated accounts, anyone could reuse a nickname.
"""

from chat.protocol import packet, valid_text


async def on_dm(server, peer, msg):
    target = msg.get("to")
    text = msg.get("text")
    if not isinstance(target, str) or not valid_text(text):
        peer.send(packet("error", text="DM needs a recipient and 1-2000 characters"))
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

