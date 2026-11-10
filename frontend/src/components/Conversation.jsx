import { useEffect, useRef, useState } from "react";
import { Avatar, Icon, shortTime } from "./Icons.jsx";

const EMPTY_ENTRIES = [];

export default function Conversation({ state, onSend, onOpenNav, onOpenAi, onOpenTransport }) {
  const [draft, setDraft] = useState("");
  const feedRef = useRef(null);
  const inputRef = useRef(null);
  const room = state.active.type === "room";
  const entries = room ? state.roomMessages[state.active.id] || EMPTY_ENTRIES : state.dmMessages[state.active.id.toLowerCase()] || EMPTY_ENTRIES;

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [entries]);

  function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || state.status !== "connected") return;
    if (onSend(text)) {
      setDraft("");
      if (inputRef.current) inputRef.current.style.height = "auto";
    }
  }

  return (
    <main className="conversation clay-card" aria-label="Conversation">
      <header className="conversation-header">
        <button className="icon-button mobile-menu" type="button" onClick={onOpenNav} aria-label="Open navigation"><Icon name="menu" /></button>
        <div className="channel-icon"><Icon name={room ? "hash" : "users"} /></div>
        <div className="header-title"><h1>{state.active.id}</h1><p>{room ? state.active.id === "lobby" ? "Your home for everyday conversation" : `The #${state.active.id} room` : `Private conversation with ${state.active.id}`}</p></div>
        <div className="header-actions">
          <span className={`connected-pill${state.status === "connected" ? " connected" : ""}`} aria-live="polite"><i /><span>{state.status === "connected" ? "Connected" : state.status === "connecting" ? "Connecting" : state.status === "reconnecting" ? "Reconnecting" : "Offline"}</span></span>
          <button className="icon-button mobile-ai" type="button" onClick={onOpenAi} aria-label="Open Chunky"><Icon name="spark" /></button>
          <button className="icon-button" type="button" onClick={onOpenTransport} aria-label="Open transport view" title="Transport view"><Icon name="code" /></button>
        </div>
      </header>

      <div className="chat-feed" ref={feedRef} role="log" aria-live="polite" aria-relevant="additions">
        {entries.length ? <><div className="chat-day"><span>TODAY</span></div>{entries.map((entry, index) => {
          if (entry.kind === "system") return <div className="system-note" key={`system-${index}`}>{entry.text}</div>;
          const mine = entry.username.toLowerCase() === state.username.toLowerCase();
          return <div className={`message-row${mine ? " self" : ""}`} key={`message-${index}`}>
            <Avatar name={entry.username} className="avatar message-avatar" />
            <div className="message-body"><div className="message-meta"><strong>{mine ? "You" : entry.username}</strong><time>{shortTime(entry.time)}</time></div><div className="bubble">{entry.text}</div></div>
          </div>;
        })}</> : <div className="empty-chat"><div className="empty-art"><Icon name="chat" /></div><h2>{room ? `Welcome to #${state.active.id}.` : `Say hello to ${state.active.id}.`}</h2><p>{room ? "Start the conversation with a message below." : "This direct message is only visible to the two of you."}</p></div>}
      </div>

      <form className="chat-composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="chatInput">Message</label>
        <textarea id="chatInput" ref={inputRef} rows={1} maxLength={2000} value={draft} disabled={state.status !== "connected"} onChange={(event) => { setDraft(event.target.value); event.target.style.height = "auto"; event.target.style.height = Math.min(event.target.scrollHeight, 150) + "px"; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} placeholder={room ? `Message #${state.active.id}...` : `Message ${state.active.id} privately...`} />
        <button className="send-button" type="submit" aria-label="Send message" disabled={state.status !== "connected"}><Icon name="send" /></button>
      </form>
      <div className="composer-foot"><span>Press <kbd>Enter</kbd> to send · <kbd>Shift + Enter</kbd> for a new line</span><span>TCP powered <span className="footer-spark">✦</span></span></div>
    </main>
  );
}
