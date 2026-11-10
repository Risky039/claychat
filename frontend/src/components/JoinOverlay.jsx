import { useState } from "react";
import { Icon } from "./Icons.jsx";

export default function JoinOverlay({ state, onJoin, onAuthenticate }) {
  const [mode, setMode] = useState("guest");
  const [nickname, setNickname] = useState(() => window.localStorage.getItem("claychat-nickname") || "");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [validationError, setValidationError] = useState("");

  async function submit(event) {
    event.preventDefault();
    const value = nickname.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]{1,19}$/.test(value)) {
      setValidationError("Use 2–20 letters, digits, or underscores; start with a letter.");
      return;
    }
    if (mode !== "guest" && password.length < 8) {
      setValidationError("Password must be at least 8 characters.");
      return;
    }
    setValidationError("");
    if (mode === "guest") {
      onJoin(value);
    } else if (onAuthenticate) {
      await onAuthenticate(mode, { username: value, password, inviteCode: inviteCode.trim() });
    }
  }

  return (
    <div className={`join-overlay${state.joined ? " hidden" : ""}`} aria-hidden={state.joined}>
      <form className="join-card clay-card" onSubmit={submit}>
        <div className="join-decoration"><div className="join-logo"><Icon name="chat" /></div></div>
        <span className="join-eyebrow">WELCOME TO CLAYCHAT</span>
        <h2>Come on in.<br /><em>Good chats await.</em></h2>
        <div className="join-tabs" role="tablist" aria-label="Entry mode">
          <button type="button" role="tab" aria-selected={mode === "guest"} className={`join-tab${mode === "guest" ? " active" : ""}`} onClick={() => { setMode("guest"); setValidationError(""); }}>Guest</button>
          <button type="button" role="tab" aria-selected={mode === "login"} className={`join-tab${mode === "login" ? " active" : ""}`} onClick={() => { setMode("login"); setValidationError(""); }}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={`join-tab${mode === "register" ? " active" : ""}`} onClick={() => { setMode("register"); setValidationError(""); }}>Create account</button>
        </div>
        <p>
          {mode === "guest"
            ? "Pick a nickname and join right away, or sign in to reserve your name and save DMs."
            : mode === "login"
              ? "Sign in with your reserved username and password."
              : "Reserve your nickname with a password so nobody else can claim it."}
        </p>
        <label htmlFor="nicknameInput">{mode === "guest" ? "Your nickname" : "Username"}</label>
        <input id="nicknameInput" value={nickname} onChange={(event) => setNickname(event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} minLength={2} maxLength={20} pattern="[A-Za-z][A-Za-z0-9_]{1,19}" placeholder="e.g. alex" required />
        {mode !== "guest" ? (
          <>
            <label htmlFor="passwordInput">Password</label>
            <input id="passwordInput" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={8} maxLength={128} placeholder="At least 8 characters" required />
          </>
        ) : null}
        {mode === "register" && state.inviteRequired ? (
          <>
            <label htmlFor="inviteInput">Invite code</label>
            <input id="inviteInput" value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="Enter invite code" required />
          </>
        ) : null}
        <div className="join-error" role="alert">{validationError || state.joinError}</div>
        <button type="submit" className="join-button" disabled={state.status === "connecting"}>
          {mode === "guest" ? "Enter as guest" : mode === "login" ? "Sign in" : "Create account"} <Icon name="arrow" />
        </button>
        <small>Live rooms · Private AI · Powered by TCP</small>
      </form>
    </div>
  );
}
