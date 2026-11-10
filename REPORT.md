# Transport-layer chat assignment report

## Implementation

`chat_server.py` uses `asyncio.start_server` to accept multiple TCP clients at port 8765. Every connection has a reader, a writer task, and a bounded outgoing queue. A client first registers a unique nickname. The server maps nicknames to live sockets, routes room messages to connected members, routes direct messages by nickname, and sends presence events when a user joins or leaves. EOF or connection error removes the user. Frames are UTF-8 JSON lines. `chat_client.py` supplies a terminal interface. The frontend in `frontend/src` uses React and a claymorphism design. Vite builds it into `frontend/dist`, which `web_app.py` serves while bridging each browser WebSocket to a separate TCP connection. Browser users and terminal users can share the same rooms. WebSockets run over TCP and are appropriate for browser-based two-way messaging. [MDN WebSocket documentation](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API/Writing_WebSocket_servers), [aiohttp WebSocket documentation](https://docs.aiohttp.org/en/stable/web_quickstart.html#websockets).

The optional `/ai` request goes from a client to the TCP server, then the server makes an HTTPS request to Meta Model API `POST /v1/chat/completions`. Its response is shown as Chunky and sent privately to the requester over the existing TCP socket. The server keeps up to six completed AI turns per connection and includes them in follow-up requests; users can inspect or reset that context. Human chat is excluded from AI context. One AI call per user can run at a time, and failed calls do not enter history. The API key resides in the server environment or a local Git-ignored file; it is never sent to a client. The current default model is `muse-spark-1.3`. Meta's [API reference](https://dev.meta.ai/docs/api-reference) documents the endpoint and bearer authentication; its [quickstart](https://dev.meta.ai/docs/quickstart) documents the model and environment variable. The Meta request uses minimal reasoning effort, a timeout, and a per-user cooldown so a slow API call does not stop other chat traffic. [Meta's reasoning guide](https://dev.meta.ai/docs/reasoning) explains that reasoning tokens count toward the completion budget.

## TCP versus UDP

1. **Why TCP?** Chat text needs to be read in the order sent and should survive ordinary packet loss. TCP provides a reliable, ordered byte stream, so the app can focus on users and routing. [TCP specification](https://datatracker.ietf.org/doc/rfc9293/).
2. **TCP guarantees.** Within a functioning connection, TCP delivers bytes without gaps or reordering to the receiving application, using acknowledgments and retransmission. It also provides flow and congestion control. It cannot guarantee that a disconnected user received or read a complete application message; persistent delivery and read receipts would require application logic. [TCP specification](https://datatracker.ietf.org/doc/rfc9293/).
3. **Differences.** TCP establishes a connection and exposes an ordered byte stream; UDP sends individual datagrams without a connection, retransmission, or delivery ordering. TCP adds connection and recovery overhead; UDP can favor timeliness for disposable updates. [TCP specification](https://datatracker.ietf.org/doc/rfc9293/), [UDP specification](https://datatracker.ietf.org/doc/html/rfc768).
4. **Possible UDP features.** Transient typing indicators, online-presence pings, or voice/video packets could use UDP if occasional loss is acceptable. This implementation uses TCP for all features.
5. **UDP loss or reordering.** A lost typing indicator simply never appears. Reordered indicators could display stale state; sequence numbers, timestamps, expiry, or application-level retransmission would be needed where correctness matters. UDP itself does not repair these cases. [UDP usage guidelines](https://www.rfc-editor.org/rfc/rfc8085.html).
6. **Sockets and ports.** The server binds a TCP listening socket to host address and port 8765. The client's socket connects to that address and port from an operating-system-assigned source port. The IP addresses and ports identify the connection endpoints; `accept` yields a separate socket for each client. The server can therefore hold several active connections at once.
7. **TCP disconnection.** An orderly close eventually gives the server EOF; a reset or transport error raises an exception. The server removes the nickname, closes its writer, and broadcasts a `left` presence event. A silent network failure may take time to detect without application heartbeats. [TCP specification](https://datatracker.ietf.org/doc/rfc9293/).

TCP has no message boundaries. The implementation adds `\n` after each JSON object and reads lines. The 8 KiB line cap limits oversized frames. A per-client outgoing queue prevents a slow reader from blocking broadcast to others. The server keeps no human-chat history; offline delivery is outside this assignment. Private AI context exists only for the current connection.

## Cloud architecture

The following architecture is implemented in `deploy_lightsail.py` and ready to provision once the AWS account allows instance creation. It is **not currently running** in AWS.

```mermaid
flowchart LR
    A[Browser: Alice] -- WebSocket 8080 --> F[Lightsail firewall]
    B[Browser: Bob] -- WebSocket 8080 --> F
    C[Terminal client] -- TCP 8765 --> F
    F --> I[Ubuntu Lightsail instance]
    I --> G[aiohttp WebSocket gateway]
    I --> R[Built React frontend]
    G -- loopback TCP / JSON lines --> S[Python asyncio TCP server / systemd]
    I --> S
    D[Private S3 deployment bundle] -- first-boot download --> I
    S -- HTTPS, optional /ai --> M[Meta Model API]
    S --> E[/etc/tcp-chat.env: Meta key]
```

**AWS services.** Lightsail supplies the Linux virtual machine, public IP, and network firewall. A private S3 bucket stores the deployment bundle for first-boot installation; the instance fetches it with a short-lived presigned URL and checks its digest. Ubuntu runs Python and `systemd`, which restarts the server and gateway on failure. Meta Model API is an external HTTPS service for optional AI replies. The firewall needs inbound TCP 8765 for terminal clients and 8080 for the browser app. The deployment script opens both ports and leaves SSH access in place. Once provisioned, the browser URL is `http://PUBLIC_IP:8080` and raw TCP clients use `PUBLIC_IP:8765`. [Lightsail firewall documentation](https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html), [S3 presigned URL documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-presigned-urls.html).

**Deployment and execution.** Run `npm install` and `npm run build` in `frontend`, install `boto3`, then run `python deploy_lightsail.py` with AWS credentials authorized for Lightsail. Wait for first boot, retrieve the instance's public IP from Lightsail, and open the browser URL in two windows with distinct nicknames. Run `python smoke_remote.py PUBLIC_IP` to create raw TCP cloud evidence. Set `MODEL_API_KEY` in `/etc/tcp-chat.env` through SSH and restart `tcp-chat` to enable `/ai`. Full commands are in [README.md](README.md).

**Current status.** On 10 November 2026, the connected AWS account successfully listed Lightsail instance plans and showed no existing instances. An attempt to create `tcp-chat-assignment-20261110` in `us-east-1a` failed with `AccessDeniedException`: an AWS Organizations service control policy explicitly denies `lightsail:CreateInstances`. EC2 and ECS operations were also denied. Consequently, no public endpoint or cloud demonstration exists yet. This report does not claim the cloud deployment requirement is met. AWS organization permission is required to complete it.

## Evidence of simultaneous messaging

`python -m unittest -v test_chat test_web_app` passed eight tests locally, including two-user raw TCP messaging, two browser WebSocket clients bridged to TCP, private AI follow-ups, reset during an active request, and error handling. The two-user transcript from the test run:

```text
alice -> lobby: Hello, Bob!   [received by both Alice and Bob]
bob -> lobby: Hi, Alice!      [received by both Alice and Bob]
alice -> bob (DM): Private hello
Ran 8 tests ... OK
```

The test also verifies room changes and disconnect cleanup. Browser QA confirmed the React claymorphism layout, two browser users communicating simultaneously, and a live assistant reply. The gateway test fetched the built JavaScript and CSS assets. `smoke_remote.py` is ready to produce `evidence/remote-demo.json` after successful cloud deployment. The AI command was tested with a mocked API response and with the provided key against the live Meta service. `evidence/ai-conversation-live.txt` records a local TCP client receiving two Meta replies, correctly recalling a codeword on the second turn, viewing two history turns, and resetting the context. The key is absent from the evidence file.

## Limitations and security

This is an academic demonstration. Usernames are nicknames, not authenticated identities. Public TCP, HTTP, and WebSocket traffic are unencrypted and chat state is in memory; restarting the instance drops connections and messages. A production deployment would need TLS (`https`/`wss` for browsers), authentication, abuse controls, durable storage, and monitored operations. No API keys, passwords, or credentials are in the repository.
