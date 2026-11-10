import { useEffect, useRef } from "react";
import { Icon, shortTime } from "./Icons.jsx";

export default function TransportDrawer({ open, events, onClose, onClear }) {
  const feedRef = useRef(null);
  useEffect(() => {
    if (open && feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [open, events]);

  return (
    <>
      {open ? <div className="drawer-backdrop" onClick={onClose} /> : null}
      <aside id="transport-panel" className={`transport-drawer${open ? " open" : ""}`} aria-label="Transport view" aria-hidden={!open} inert={!open}>
        <div className="drawer-header"><div><span className="drawer-eyebrow">UNDER THE HOOD</span><h2>Transport view</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close transport view" data-panel-close><Icon name="close" /></button></div>
        <div className="transport-explainer"><div className="transport-route"><span>Browser</span><b>WebSocket</b><span>Gateway</span><b>TCP socket</b><span>Chat server</span></div><p>Browser frames are bridged to newline-delimited JSON over TCP. The gateway opens one TCP connection for each browser client.</p></div>
        <div className="log-heading"><h3>Live protocol events</h3><button className="clear-events" type="button" onClick={onClear}>Clear</button></div>
        <div className="event-log" ref={feedRef} role="log" aria-live="polite">
          {events.length ? events.map((entry, index) => <div className={`event-item ${entry.direction}`} key={index}><div className="event-item-head"><strong>{entry.direction === "out" ? "CLIENT → SERVER" : "SERVER → CLIENT"}</strong><time>{shortTime(entry.time)}</time></div><code>{JSON.stringify(entry.item, null, 2)}</code></div>) : <div className="event-empty">Connect to see protocol events here.</div>}
        </div>
      </aside>
    </>
  );
}
