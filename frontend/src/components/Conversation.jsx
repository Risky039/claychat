import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Avatar, Icon, shortTime } from "./Icons.jsx";
import { ALLOWED_EMOJI, dayLabel } from "../messages.js";

const EMPTY_ENTRIES = [];

function entryKey(entry) {
  return entry ? `${entry.id ?? ""}|${entry.kind}|${entry.time ?? ""}|${entry.text}` : "";
}

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Conversation({
  state,
  inert,
  panel,
  onSend,
  onNotifyTyping,
  onEdit,
  onDelete,
  onReact,
  onMarkRead,
  onUpload,
  onLoadOlder,
  onOpenPanel,
}) {
  const [draft, setDraft] = useState("");
  const [messageOptions, setMessageOptions] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editingText, setEditingText] = useState("");
  const [pendingAttachment, setPendingAttachment] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const feedRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);
  const lastReadRef = useRef(0);
  const atBottom = useRef(true);
  const scrollMemo = useRef({ channel: "", first: "", last: "", height: 0 });
  const room = state.active.type === "room";
  const channel = `${state.active.type}:${state.active.id.toLowerCase()}`;
  const dmKey = state.active.id.toLowerCase();
  const entries = room ? state.roomMessages[state.active.id] || EMPTY_ENTRIES : state.dmMessages[dmKey] || EMPTY_ENTRIES;
  const hasMore = room ? state.roomHasMore[state.active.id] : state.dmHasMore[dmKey];
  const loadingOlder = room ? state.roomLoadingOlder[state.active.id] : state.dmLoadingOlder[dmKey];
  const typingUsers = (state.typingByChannel?.[channel] || []).filter(
    (u) => u.toLowerCase() !== state.username.toLowerCase()
  );

  // New message at the bottom or switched channel: go to the bottom.
  // Older messages added on top: keep the reader's place.
  useLayoutEffect(() => {
    const feed = feedRef.current;
    if (!feed) return;
    const first = entryKey(entries[0]);
    const last = entryKey(entries[entries.length - 1]);
    const memo = scrollMemo.current;
    if (channel !== memo.channel || last !== memo.last) {
      feed.scrollTop = feed.scrollHeight;
      atBottom.current = true;
    }
    else if (first !== memo.first) feed.scrollTop += feed.scrollHeight - memo.height;
    scrollMemo.current = { channel, first, last, height: feed.scrollHeight };
  }, [channel, entries]);

  useEffect(() => {
    const feed = feedRef.current;
    const observer = new ResizeObserver(() => {
      if (atBottom.current) feed.scrollTop = feed.scrollHeight;
    });
    observer.observe(feed);
    return () => observer.disconnect();
  }, []);

  // Automatically send read receipt for the latest message from someone else in the active channel
  useEffect(() => {
    if (state.status !== "connected" || !onMarkRead) return;
    for (let i = entries.length - 1; i >= 0; i -= 1) {
      const entry = entries[i];
      if (entry.id != null && entry.username && entry.username.toLowerCase() !== state.username.toLowerCase()) {
        if (entry.id > lastReadRef.current) {
          lastReadRef.current = entry.id;
          onMarkRead(entry.id);
        }
        break;
      }
    }
  }, [entries, state.status, state.username, onMarkRead]);

  async function handleFileSelect(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onUpload) return;
    setUploading(true);
    setUploadError("");
    try {
      const uploaded = await onUpload(file);
      setPendingAttachment(uploaded);
    } catch (err) {
      setUploadError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if ((!text && !pendingAttachment) || state.status !== "connected") return;
    if (onSend(text, pendingAttachment?.id || null)) {
      setDraft("");
      setPendingAttachment(null);
      setUploadError("");
      if (inputRef.current) inputRef.current.style.height = "auto";
    }
  }

  function submitEdit(event, id) {
    event.preventDefault();
    const next = editingText.trim();
    if (!next) return;
    if (onEdit) onEdit(id, next);
    setEditingId(null);
    setEditingText("");
  }

  return (
    <main className="conversation clay-card" aria-label="Conversation" inert={inert}>
      <header className="conversation-header">
        <button className="icon-button mobile-menu" type="button" onClick={onOpenPanel} aria-label="Open navigation" aria-controls="navigation-panel" aria-expanded={panel === "navigation-panel"}><Icon name="menu" /></button>
        <div className="channel-icon"><Icon name={room ? "hash" : "users"} /></div>
        <div className="header-title"><h1>{state.active.id}</h1><p>{room ? state.active.id === "lobby" ? "Your home for everyday conversation" : `The #${state.active.id} room` : `Private conversation with ${state.active.id}`}</p></div>
        <div className="header-actions">
          <span className={`connected-pill${state.status === "connected" ? " connected" : ""}`} role="status"><i /><span>{state.status === "connected" ? "Connected" : state.status === "connecting" ? "Connecting" : state.status === "reconnecting" ? "Reconnecting" : "Offline"}</span></span>
          <button className="icon-button mobile-ai" type="button" onClick={onOpenPanel} aria-label="Open Chunky" aria-controls="assistant-panel" aria-expanded={panel === "assistant-panel"}><Icon name="spark" /></button>
          <button className="icon-button" type="button" onClick={onOpenPanel} aria-label="Open transport view" aria-controls="transport-panel" aria-expanded={panel === "transport-panel"} title="Transport view"><Icon name="code" /></button>
        </div>
      </header>

      <div className="chat-feed" ref={feedRef} role="log" aria-live="polite" aria-relevant="additions" onScroll={(event) => {
        const feed = event.currentTarget;
        atBottom.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 32;
      }}>
        {entries.length ? <>{hasMore ? <div className="load-older"><button type="button" onClick={() => onLoadOlder(state.active.id)} disabled={loadingOlder || state.status !== "connected"}>{loadingOlder ? "Loading..." : "Load earlier messages"}</button></div> : null}{entries.map((entry, index) => {
          const day = dayLabel(entry.time);
          const divider = day && day !== dayLabel(entries[index - 1]?.time) ? <div className="chat-day" key={`day-${index}`}><span>{day}</span></div> : null;
          if (entry.kind === "system") return [divider, <div className="system-note" key={`system-${index}`}>{entry.text}</div>];
          const mine = entry.username.toLowerCase() === state.username.toLowerCase();
          const reactions = entry.reactions || {};
          const reactionEntries = Object.entries(reactions).filter(([, list]) => list && list.length > 0);
          const readers = entry.id != null ? state.readByMessage?.[entry.id] || [] : [];
          const optionsKey = `${channel}:${entry.id}`;
          const optionsOpen = messageOptions === optionsKey;
          return [divider, <div className={`message-row${mine ? " self" : ""}`} key={entry.id != null ? `message-${entry.id}` : `message-${index}`}>
            <Avatar name={entry.username} className="avatar message-avatar" />
            <div className="message-body">
              <div className="message-meta">
                <strong>{mine ? "You" : entry.username}</strong>
                <time>{shortTime(entry.time)}</time>
                {entry.edited_at ? <span className="edited-tag">(edited)</span> : null}
                {entry.id != null ? (
                  <button className="message-options" type="button" aria-label="Message actions" aria-expanded={optionsOpen} aria-controls={`message-actions-${entry.id}`} onClick={() => setMessageOptions(optionsOpen ? null : optionsKey)}>
                    <Icon name="more" />
                  </button>
                ) : null}
              </div>
              {editingId === entry.id ? (
                <form className="edit-form" onSubmit={(ev) => submitEdit(ev, entry.id)}>
                  <input aria-label="Edit message" value={editingText} onChange={(ev) => setEditingText(ev.target.value)} maxLength={2000} autoFocus />
                  <button type="submit">Save</button>
                  <button type="button" onClick={() => setEditingId(null)}>Cancel</button>
                </form>
              ) : (
                <div className="bubble">
                  {entry.attachment ? (
                    entry.attachment.mime?.startsWith("image/") ? (
                      <a href={entry.attachment.url} target="_blank" rel="noreferrer" className="attachment-image-link">
                        <img src={entry.attachment.url} alt={entry.attachment.name} className="attachment-image" loading="lazy" />
                      </a>
                    ) : (
                      <a href={entry.attachment.url} target="_blank" rel="noreferrer" className="attachment-file">
                        📎 {entry.attachment.name} <small>({formatSize(entry.attachment.size)})</small>
                      </a>
                    )
                  ) : null}
                  {entry.text ? <div>{entry.text}</div> : null}
                </div>
              )}
              {entry.id != null ? (
                <div id={`message-actions-${entry.id}`} className={`message-actions${optionsOpen ? " is-open" : ""}`}>
                  <div className="emoji-picker-row">
                    {ALLOWED_EMOJI.map((emoji) => (
                      <button key={emoji} type="button" className="emoji-quick" onClick={() => onReact && onReact(entry.id, emoji)} title={`React with ${emoji}`}>{emoji}</button>
                    ))}
                  </div>
                  {mine && editingId !== entry.id ? (
                    <div className="author-actions">
                      <button type="button" onClick={() => { setEditingId(entry.id); setEditingText(entry.text || ""); }}>Edit</button>
                      <button type="button" onClick={() => onDelete && onDelete(entry.id)}>Delete</button>
                    </div>
                  ) : null}
                </div>
              ) : null}
              {reactionEntries.length ? (
                <div className="reaction-pills">
                  {reactionEntries.map(([emoji, users]) => {
                    const reacted = users.some((u) => u.toLowerCase() === state.username.toLowerCase());
                    return (
                      <button key={emoji} type="button" className={`reaction-pill${reacted ? " active" : ""}`} onClick={() => onReact && onReact(entry.id, emoji)} title={users.join(", ")}>
                        <span>{emoji}</span><strong>{users.length}</strong>
                      </button>
                    );
                  })}
                </div>
              ) : null}
              {mine && readers.length ? <div className="read-receipt">Seen by {readers.join(", ")}</div> : null}
            </div>
          </div>];
        })}</> : <div className="empty-chat"><div className="empty-art"><Icon name="chat" /></div><h2>{room ? `Welcome to #${state.active.id}.` : `Say hello to ${state.active.id}.`}</h2><p>{room ? "Start the conversation with a message below." : "This direct message is only visible to the two of you."}</p></div>}
      </div>

      {typingUsers.length ? <div className="typing-bar" aria-live="polite">{typingUsers.join(", ")} {typingUsers.length === 1 ? "is" : "are"} typing…</div> : null}
      {pendingAttachment ? (
        <div className="pending-attachment">
          <span>📎 {pendingAttachment.name} ({formatSize(pendingAttachment.size)})</span>
          <button type="button" onClick={() => setPendingAttachment(null)} aria-label="Remove attachment">✕</button>
        </div>
      ) : null}
      {uploadError ? <div className="upload-error" role="alert">{uploadError}</div> : null}

      <form className="chat-composer" onSubmit={submit}>
        <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,.txt,.md,.json,.csv" hidden onChange={handleFileSelect} />
        <button type="button" className="attach-button" onClick={() => fileInputRef.current?.click()} disabled={state.status !== "connected" || uploading} title="Attach image or file" aria-label="Attach image or file">{uploading ? "…" : "📎"}</button>
        <label className="sr-only" htmlFor="chatInput">Message</label>
        <textarea id="chatInput" ref={inputRef} rows={1} maxLength={2000} value={draft} disabled={state.status !== "connected"} onChange={(event) => { setDraft(event.target.value); if (onNotifyTyping && event.target.value.trim()) onNotifyTyping(); event.target.style.height = "auto"; event.target.style.height = Math.min(event.target.scrollHeight, 150) + "px"; }} onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !window.matchMedia("(pointer: coarse)").matches) {
            event.preventDefault();
            event.currentTarget.form.requestSubmit();
          }
        }} placeholder={room ? `Message #${state.active.id}...` : `Message ${state.active.id} privately...`} />
        <button className="send-button" type="submit" aria-label="Send message" disabled={state.status !== "connected"} onPointerDown={(event) => {
          if (document.activeElement === inputRef.current) event.preventDefault();
        }}><Icon name="send" /></button>
      </form>
      <div className="composer-foot"><span>Press <kbd>Enter</kbd> to send · <kbd>Shift + Enter</kbd> for a new line</span><span>TCP powered <span className="footer-spark">✦</span></span></div>
    </main>
  );
}
