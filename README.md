# TCP Chat with Chunky

A multi-user Python chat application with a React claymorphism browser interface. Human chat uses ordinary TCP sockets and newline-delimited JSON. A same-origin WebSocket gateway lets browsers use that TCP server. Chunky is the private, multi-turn assistant powered by Meta Model API.

## Run locally

Python 3.9+ and Node.js 20.19+ are required. The terminal server and client use only the Python standard library; the browser gateway needs `aiohttp`. Build the React frontend once before starting the gateway:

```sh
cd frontend
npm install
npm run build
cd ..
```

Terminal 1:

```sh
python -m pip install -r requirements.txt
python web_app.py
```

Open `http://127.0.0.1:8080` in a browser. Join with a nickname. Open the same URL in another browser or private window with a second nickname to demonstrate simultaneous users. React manages the conversation, rooms, people, AI panel, and transport inspector; the Python gateway serves its Vite production build. The web app also starts the raw TCP listener on port 8765, so terminal clients still work:

Terminal 2:

```sh
python chat_client.py alice
```

Terminal 3:

```sh
python chat_client.py bob
```

Type a message to send it to the current room. Terminal commands: `/join study`, `/dm bob hello`, `/users`, `/ai Explain TCP`, `/ai-history`, `/ai-reset`, `/quit`. In the browser, use the room list, people list, private Chunky panel, and the `</>` transport inspector.

To enable Chunky, set `MODEL_API_KEY` in the **server's** environment before starting it, or save the key in `deployment-private/meta_model_api_key` (a local, Git-ignored file). The environment variable takes precedence. Set `META_MODEL` to override the default `muse-spark-1.3`. The key is never needed by clients. Without it, chat works and `/ai` returns a configuration error.

PowerShell:

```powershell
$env:MODEL_API_KEY = "YOUR_KEY_FROM_META_DASHBOARD"
python chat_server.py
```

Do not commit a key or paste one into the deployment script. The example above is a placeholder.

A live two-turn conversation is recorded in `evidence/ai-conversation-live.txt`. The server uses minimal reasoning effort so the model leaves room in the completion budget for visible chat text, as described in [Meta's reasoning documentation](https://dev.meta.ai/docs/reasoning).

Each connected user has a private AI conversation. The server sends up to the last six completed turns with each new `/ai` prompt, keeping follow-up questions in context. `/ai-history` shows those turns to that user; `/ai-reset` clears them. Context is held in memory and disappears on disconnect or server restart. One AI request per user is active at a time, and requests have a five-second cooldown. Human room and direct messages are never added to the AI context.

## Protocol

Each TCP connection starts with `{"type":"hello","username":"alice"}`. Every subsequent frame is a UTF-8 JSON object followed by `\n`. The server replies with `welcome`, `message`, `dm`, `presence`, `users`, `joined`, `ai_status`, `ai`, `ai_history`, `ai_reset`, or `error` events. Client requests use `message`, `dm`, `join`, `users`, `ai`, `ai_history`, `ai_reset`, and `quit`. One connection represents one active username. New clients join `lobby`. The gateway maps each browser WebSocket connection to its own TCP connection and forwards these JSON objects; it does not replace the TCP chat server.

Example:

```json
{"type":"message","text":"Hello, Bob!"}
```

```json
{"type":"message","room":"lobby","username":"alice","text":"Hello, Bob!","time":"2026-11-10T12:00:00+00:00"}
```

TCP is a byte stream, so the newline is the application framing rule. A single `recv` call need not equal one message. Message text is limited to 2,000 characters. Usernames are unique while connected. The server removes users and broadcasts a departure on disconnect.

## Verify

```sh
cd frontend && npm test && npm run build && cd ..
python -m unittest -v test_store test_history test_auth test_rich_chat test_smarter_ai test_chat test_web_app
```

The test suites cover SQLite WAL persistence and schema migrations, room and DM history pagination, `scrypt` password hashing and session tokens, rate limiting and connection timeouts, typing indicators, message edit/delete permissions, emoji reactions, read receipts, magic-byte validated file uploads, SSE streaming AI replies, `@ai` room mentions, `/summarize`, two concurrent TCP users, and WebSocket gateway bridging. For a live server, run:

```sh
python smoke_remote.py SERVER_PUBLIC_IP --port 8765
```

It writes `evidence/remote-demo.json` only after both users have received both messages. See [REPORT.md](REPORT.md) for transport analysis and deployment status.

## Expanded product features

- **Modular `chat/` package & SQLite WAL storage (`chat/store.py`):** Every message receives an integer `id`. Joining a room delivers recent history (`history`), and clients can page backward with `{"type":"history","room":"...","before":id}`.
- **Accounts, sessions & security (`chat/auth.py`, `chat/ratelimit.py`):** Optional account registration (`POST /api/register`), sign-in (`POST /api/login`), and logout (`POST /api/logout`) using `hashlib.scrypt` and `HttpOnly; SameSite=Lax` session cookies (`claychat_session`). Registered nicknames cannot be impersonated by guests, and authenticated users unlock persistent DM history (`dm_history`). Set `CHAT_INVITE_CODE` to require an invite code on sign-up. Includes token-bucket rate limiting and hello/idle socket timeouts.
- **Richer chat (`chat/handlers/rooms.py`, `chat/uploads.py`):** Live typing indicators (`typing`), author-only message editing (`edit` -> `message_updated`) and soft deletion (`delete` -> `message_deleted`), 8-emoji reaction toggles (`react` -> `reactions_updated`), read receipts (`read` -> `read_receipt`), and 5 MB magic-byte validated image/file attachments (`POST /api/uploads` & `GET /api/uploads/{id}`).
- **Smarter AI (`chat/ai.py`):** Token-by-token Server-Sent Events streaming (`stream: true` -> `ai_delta` chunks), shared room mentions (`@ai` or `@chunky` in a room message), and private room summaries (`summarize` or the **TL;DR** button in the Chunky panel).

## Supabase Postgres on Render

ClayChat can store accounts, sessions, chat history, reactions, and read receipts in a private `claychat` schema on PostgreSQL. The backend creates and updates the schema on startup.

1. In Supabase, open **Connect → Session pooler** and copy the Postgres URI. Replace the password placeholder with the project's database password, URL-encoding any reserved characters in it.
2. In the Render service's **Environment** settings, set `CHAT_DATABASE_URL` to that URI. Store the value there as a secret and deploy the new build. The application does not use Supabase publishable or secret API keys.
3. Confirm that `/readyz` returns HTTP 200. The startup log identifies the storage backend without printing the connection URI.

If a password is hard to embed in a URI, set `CHAT_DATABASE_PASSWORD` in Render to the raw database password. This value overrides the password from `CHAT_DATABASE_URL`. Keep both settings on the server.

An unset `CHAT_DATABASE_URL` keeps the SQLite setup for local use. A configured Postgres connection failure stops startup. Switching backends does not import old SQLite records. Uploaded file contents still use `CHAT_UPLOAD_DIR`, so they need their own durable storage if they must survive Render redeploys.

## Docker & Caddy HTTPS deployment

Run the full stack (non-root Python/React container + Caddy automatic TLS reverse proxy + persistent volume for SQLite and uploads):

```sh
CHAT_DOMAIN=chat.example.com MODEL_API_KEY=your_key docker compose up -d --build
```

Health and readiness probes are exposed at `/healthz` and `/readyz`.

## Azure VM deployment

See [AZURE_DEPLOY.md](AZURE_DEPLOY.md) for the portal setup, PowerShell upload commands, VM service setup script, private Chunky key configuration, architecture diagram, and two-user verification.

## AWS Lightsail deployment

The included script uploads the Python server and built React assets to a private, encrypted S3 bucket, creates an Ubuntu 24.04 Lightsail instance in `us-east-1a`, installs the TCP server and browser gateway as a `systemd` service, and opens TCP ports 8765 and 8080. Run `npm run build` first. It requires AWS credentials with S3 bucket/object permissions plus Lightsail create and firewall permissions. Set `CHAT_DEPLOY_BUCKET` to use an existing private bucket; otherwise the script creates one. The instance downloads the bundle through a one-hour presigned URL and checks its SHA-256 digest. Instance and S3 charges apply while those resources exist.

```sh
python -m pip install boto3
python deploy_lightsail.py
```

In Lightsail, find the instance's public IP, wait for first boot to finish, then open `http://SERVER_PUBLIC_IP:8080` or connect with terminal clients:

```sh
python chat_client.py alice --host SERVER_PUBLIC_IP
python chat_client.py bob --host SERVER_PUBLIC_IP
python smoke_remote.py SERVER_PUBLIC_IP
```

To enable Chunky on the instance, use the Lightsail SSH console and create a root-owned environment file outside the repository:

```sh
sudo install -m 600 -o root -g root /dev/null /etc/tcp-chat.env
sudo nano /etc/tcp-chat.env
# Add one line: MODEL_API_KEY=your_actual_key
sudo systemctl restart tcp-chat
sudo systemctl status tcp-chat
```

The currently connected AWS role is denied `lightsail:CreateInstances` by an organization service control policy, so this deployment has **not** succeeded in the connected account. No public IP or cloud transcript is claimed. The AWS administrator must permit the operation, or deployment must use an account where it is allowed. The script creates a public academic demo with nickname-only identity and plaintext TCP/HTTP/WebSocket; add TLS and authentication before use with private content.
