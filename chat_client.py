"""Terminal client for the newline-delimited JSON TCP protocol."""

import argparse
import json
import socket
import threading


def receive(sock):
    try:
        with sock.makefile("r", encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                kind = item.get("type")
                if kind in ("message", "dm", "ai"):
                    label = f"[{item.get('room', 'DM')}]" if kind == "message" else f"[{kind.upper()}]"
                    print(f"\n{label} {item.get('username')}: {item.get('text')}", flush=True)
                elif kind == "presence":
                    print(f"\n* {item['username']} {item['action']}", flush=True)
                elif kind == "ai_status":
                    print("\n[AI] Thinking...", flush=True)
                elif kind == "ai_history":
                    print(f"\n[AI] {item['turns']} saved turns in this connection:", flush=True)
                    for entry in item["messages"]:
                        print(f"  {entry['role']}: {entry['content']}", flush=True)
                elif kind == "ai_reset":
                    print("\n[AI] Conversation cleared", flush=True)
                else:
                    print(f"\n{json.dumps(item, ensure_ascii=False)}", flush=True)
    except (OSError, ValueError):
        pass
    print("\nDisconnected from server", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.settimeout(None)
        threading.Thread(target=receive, args=(sock,), daemon=True).start()

        def send(**item):
            sock.sendall((json.dumps(item, ensure_ascii=False) + "\n").encode())

        send(type="hello", username=args.username)
        print("Commands: /join ROOM, /dm USER MESSAGE, /users, /ai PROMPT, /ai-history, /ai-reset, /quit. Plain text goes to the room.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                line = "/quit"
            if line == "/quit":
                send(type="quit")
                break
            if line.startswith("/join "):
                send(type="join", room=line[6:].strip())
            elif line.startswith("/dm "):
                parts = line.split(" ", 2)
                if len(parts) == 3:
                    send(type="dm", to=parts[1], text=parts[2])
            elif line == "/users":
                send(type="users")
            elif line == "/ai-history":
                send(type="ai_history")
            elif line == "/ai-reset":
                send(type="ai_reset")
            elif line.startswith("/ai "):
                send(type="ai", text=line[4:])
            elif line:
                send(type="message", text=line)


if __name__ == "__main__":
    main()
