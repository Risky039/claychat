import { useState } from "react";
import { Avatar, Icon } from "./Icons.jsx";

export default function Sidebar({ state, open, onClose, onJoinRoom, onSelectDm }) {
  const [roomFormOpen, setRoomFormOpen] = useState(false);
  const [roomName, setRoomName] = useState("");

  function submitRoom(event) {
    event.preventDefault();
    const room = roomName.trim();
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,29}$/.test(room)) return;
    onJoinRoom(room);
    setRoomName("");
    setRoomFormOpen(false);
    onClose();
  }

  return (
    <aside className={`sidebar clay-card${open ? " open" : ""}`} aria-label="Chat navigation">
      <div className="brand-row">
        <div className="brand-mark" aria-hidden="true"><Icon name="chat" /></div>
        <div><strong className="brand-name">claychat<span>.</span></strong><small>Where conversations feel good</small></div>
        <button className="icon-button sidebar-close" type="button" onClick={onClose} aria-label="Close navigation"><Icon name="close" /></button>
      </div>

      <div className="workspace-label">YOUR SPACE <span className="tiny-star">✦</span></div>
      <section className="nav-section" aria-labelledby="roomsHeading">
        <div className="section-heading"><h2 id="roomsHeading">Rooms</h2><button className="icon-button small" type="button" onClick={() => setRoomFormOpen((value) => !value)} aria-label="Join a room"><Icon name="plus" /></button></div>
        <div className="room-list">
          {state.rooms.map((room) => (
            <button
              key={room}
              type="button"
              className={`nav-item${state.active.type === "room" && state.active.id === room ? " active" : ""}`}
              onClick={() => { if (state.status === "connected") { onJoinRoom(room); onClose(); } }}
            >
              <Icon name="hash" /><span>{room}</span>
              {state.roomUnread[room] ? <span className="nav-badge">{state.roomUnread[room]}</span> : null}
            </button>
          ))}
        </div>
        {roomFormOpen ? <form className="room-form" onSubmit={submitRoom}><label className="sr-only" htmlFor="roomName">Room name</label><input id="roomName" value={roomName} onChange={(event) => setRoomName(event.target.value)} maxLength={30} placeholder="Room name" pattern="[A-Za-z][A-Za-z0-9_-]{0,29}" required autoFocus /><button type="submit" aria-label="Join room" disabled={state.status !== "connected"}><Icon name="arrow" /></button></form> : null}
      </section>

      <section className="nav-section people-section" aria-labelledby="peopleHeading">
        <div className="section-heading"><h2 id="peopleHeading">People here</h2><span className="count-pill">{state.users.length}</span></div>
        <div className="people-list">
          {state.users.length ? state.users.map((name) => {
            const self = name.toLowerCase() === state.username.toLowerCase();
            const active = state.active.type === "dm" && state.active.id.toLowerCase() === name.toLowerCase();
            return (
              <button key={name} type="button" className={`nav-item person-button${active ? " active" : ""}`} disabled={self} onClick={() => { onSelectDm(name); onClose(); }}>
                <Avatar name={name} /><span className="person-copy"><span>{name}{self ? " (you)" : ""}</span><small className="person-status">Online now</small></span>
                {state.dmUnread[name.toLowerCase()] ? <span className="nav-badge">{state.dmUnread[name.toLowerCase()]}</span> : null}
              </button>
            );
          }) : <p className="muted-hint">{state.status === "connected" ? "Nobody is here yet." : "Join to see who's online."}</p>}
        </div>
      </section>

      <div className="sidebar-bottom">
        <div className="tip-card"><div className="tip-icon"><Icon name="spark" /></div><div><strong>Need a hand?</strong><p>Ask Chunky in your private panel.</p></div></div>
        <div className="profile-card"><Avatar name={state.username} className="avatar self-avatar" /><div className="profile-copy"><strong>{state.username || "Your space"}</strong><small>{state.status === "connected" ? "Online now" : state.status === "reconnecting" ? "Reconnecting" : "Waiting to connect"}</small></div><span className={`online-dot${state.status === "connected" ? " connected" : ""}`} /></div>
      </div>
    </aside>
  );
}
