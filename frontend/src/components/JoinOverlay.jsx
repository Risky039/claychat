import { useState } from "react";
import { Icon } from "./Icons.jsx";

export default function JoinOverlay({ state, onJoin }) {
  const [nickname, setNickname] = useState(() => window.localStorage.getItem("claychat-nickname") || "");
  const [validationError, setValidationError] = useState("");

  function submit(event) {
    event.preventDefault();
    const value = nickname.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]{1,19}$/.test(value)) {
      setValidationError("Use 2–20 letters, digits, or underscores; start with a letter.");
      return;
    }
    setValidationError("");
    onJoin(value);
  }

  return (
    <div className={`join-overlay${state.joined ? " hidden" : ""}`} aria-hidden={state.joined}>
      <form className="join-card clay-card" onSubmit={submit}>
        <div className="join-decoration"><div className="join-logo"><Icon name="chat" /></div><div className="floating-spark">✦</div></div>
        <span className="join-eyebrow">WELCOME TO CLAYCHAT</span>
        <h2>Come on in.<br /><em>Good chats await.</em></h2>
        <p>Pick a nickname and join the conversation. No account needed for this demo.</p>
        <label htmlFor="nicknameInput">Your nickname</label>
        <input id="nicknameInput" value={nickname} onChange={(event) => setNickname(event.target.value)} autoComplete="nickname" spellCheck={false} minLength={2} maxLength={20} pattern="[A-Za-z][A-Za-z0-9_]{1,19}" placeholder="e.g. alex" required />
        <div className="join-error" role="alert">{validationError || state.joinError}</div>
        <button type="submit" className="join-button" disabled={state.status === "connecting"}>Enter the chat <Icon name="arrow" /></button>
        <small>Live rooms · Private AI · Powered by TCP</small>
      </form>
    </div>
  );
}
