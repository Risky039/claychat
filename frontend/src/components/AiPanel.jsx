import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icons.jsx";

function MarkdownText({ text }) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    return part;
  });
}

export default function AiPanel({ state, open, inert, onClose, onSend, onSummarize, onHistory, onReset }) {
  const [draft, setDraft] = useState("");
  const feedRef = useRef(null);
  const inputRef = useRef(null);
  const ready = state.status === "connected" && !state.aiPending;

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [state.aiMessages, state.aiPending]);

  function submit(text) {
    const prompt = text.trim();
    if (!prompt || !ready) return;
    if (onSend(prompt)) {
      setDraft("");
      if (inputRef.current) inputRef.current.style.height = "auto";
    }
  }

  return (
    <aside id="assistant-panel" className={`ai-panel clay-card${open ? " open" : ""}`} aria-label="Chunky assistant" inert={inert}>
      <header className="ai-header"><div className="ai-orb" aria-hidden="true"><Icon name="spark" /></div><div className="ai-heading"><h2>Chunky</h2><p>Your private thinking space</p></div><button className="icon-button ai-mobile-close" type="button" onClick={onClose} aria-label="Close Chunky" data-panel-close><Icon name="close" /></button></header>
      <div className="ai-toolbar"><span className="ai-private"><span className="tiny-lock">●</span> Private · or type <code>@ai</code> in room</span><div>{onSummarize ? <button className="text-icon-button" type="button" onClick={() => ready && onSummarize()} disabled={!ready} title={`Summarize #${state.currentRoom}`} aria-label="Summarize current room">TL;DR</button> : null}<button className="text-icon-button" type="button" onClick={onHistory} title="Show AI history" aria-label="Show AI history"><Icon name="clock" /></button><button className="text-icon-button" type="button" onClick={onReset} title="New AI conversation" aria-label="New AI conversation"><Icon name="refresh" /></button></div></div>
      <div className="ai-feed" ref={feedRef} role="log" aria-live="polite" aria-relevant="additions">
        {!state.aiMessages.length && !state.aiPending ? <div className="ai-welcome"><div className="ai-welcome-icon"><Icon name="spark" /></div><h3>Ideas, answers, and a little magic.</h3><p>Ask a question or pick a prompt below. Your conversation stays private.</p><div className="suggestions"><button type="button" className="suggestion" onClick={() => submit("Explain how TCP makes real-time chat reliable.")}>Explain TCP simply <Icon name="arrow" /></button><button type="button" className="suggestion" onClick={() => submit("Give me three creative icebreakers for a group chat.")}>Give me an icebreaker <Icon name="arrow" /></button></div></div> : state.aiMessages.map((item, index) => <div className={`ai-message ${item.role === "user" ? "user" : item.role === "error" ? "error" : "assistant"}`} key={index}><div className="ai-label">{item.role === "user" ? "YOU" : item.role === "error" ? "NOTICE" : "CHUNKY"}</div><div className="ai-bubble">{item.role === "assistant" ? <MarkdownText text={item.content} /> : item.content}</div></div>)}
        {state.aiPending ? <div className="ai-message assistant"><div className="ai-label">CHUNKY</div><div className="ai-bubble"><div className="ai-thinking"><i /><i /><i /></div></div></div> : null}
      </div>
      <form className="ai-composer" onSubmit={(event) => { event.preventDefault(); submit(draft); }}><label className="sr-only" htmlFor="aiInput">Ask Chunky</label><textarea id="aiInput" ref={inputRef} rows={1} maxLength={2000} placeholder="Ask Chunky anything..." value={draft} disabled={!ready} onChange={(event) => { setDraft(event.target.value); event.target.style.height = "auto"; event.target.style.height = Math.min(event.target.scrollHeight, 150) + "px"; }} onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !window.matchMedia("(pointer: coarse)").matches) {
          event.preventDefault();
          event.currentTarget.form.requestSubmit();
        }
      }} /><button className="ai-send" type="submit" aria-label="Send to Chunky" disabled={!ready} onPointerDown={(event) => {
        if (document.activeElement === inputRef.current) event.preventDefault();
      }}><Icon name="arrow" /></button></form>
      <p className="ai-note">AI can make mistakes. Check important answers.</p>
    </aside>
  );
}
