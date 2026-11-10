import { useLayoutEffect, useRef, useState } from "react";
import { Avatar, Icon, shortTime } from "./Icons.jsx";
import { dayLabel } from "../messages.js";

const EMPTY_ENTRIES = [];

function entryKey(entry) {
  return entry ? `${entry.id ?? ""}|${entry.kind}|${entry.time ?? ""}|${entry.text}` : "";
}

export default function Conversation({ state, onSend, onLoadOlder, onOpenNav, onOpenAi, onOpenTransport }) {
  const [draft, setDraft] = useState("");
  const feedRef = useRef(null);
  const inputRef = useRef(null);
  const scrollMemo = useRef({ channel: "", first: "", last: "", height: 0 });
  const room = state.active.type === "room";
  const channel = `${state.active.type}:${state.active.id.toLowerCase()}`;
  const dmKey = state.active.id.toLowerCase();
  const entries = room ? state.roomMessages[state.active.id] || EMPTY_ENTRIES : state.dmMessages[dmKey] || EMPTY_ENTRIES;
  const hasMore = room ? state.roomHasMore[state.active.id] : state.dmHasMore[dmKey];
  const loadingOlder = room ? state.roomLoadingOlder[state.active.id] : state.dmLoadingOlder[dmKey];

  // New message at the bottom or switched channel: go to the bottom.
  // Older messages added on top: keep the reader's place.
  useLayoutEffect(() => {
    const feed = feedRef.current;
    if (!feed) return;
    const first = entryKey(entries[0]);
    const last = entryKey(entries[entries.length - 1]);
    const memo = scrollMemo.current;
    if (channel !== memo.channel || last !== memo.last) feed.scrollTop = feed.scrollHeight;
    else if (first !== memo.first) feed.scrollTop += feed.scrollHeight - memo.height;
    scrollMemo.current = { channel, first, last, height: feed.scrollHeight };
  }, [channel, entries]);

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
        {entries.length ? <>{hasMore ? <div className="load-older"><button type="button" onClick={() => onLoadOlder(state.active.id)} disabled={loadingOlder || state.status !== "connected"}>{loadingOlder ? "Loading..." : "Load earlier messages"}</button></div> : null}{entries.map((entry, index) => {
          const day = dayLabel(entry.time);
          const divider = day && day !== dayLabel(entries[index - 1]?.time) ? <div className="chat-day" key={`day-${index}`}><span>{day}</span></div> : null;
          if (entry.kind === "system") return [divider, <div className="system-note" key={`system-${index}`}>{entry.text}</div>];
          const mine = entry.username.toLowerCase() === state.username.toLowerCase();
          return [divider, <div className={`message-row${mine ? " self" : ""}`} key={entry.id != null ? `message-${entry.id}` : `message-${index}`}>
            <Avatar name={entry.username} className="avatar message-avatar" />
            <div className="message-body"><div className="message-meta"><strong>{mine ? "You" : entry.username}</strong><time>{shortTime(entry.time)}</time></div><div className="bubble">{entry.text}</div></div>
          </div>];
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
