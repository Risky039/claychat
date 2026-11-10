import { useEffect, useRef, useState } from "react";
import { useChat } from "./useChat.js";
import { IconSprite } from "./components/Icons.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Conversation from "./components/Conversation.jsx";
import AiPanel from "./components/AiPanel.jsx";
import TransportDrawer from "./components/TransportDrawer.jsx";
import JoinOverlay from "./components/JoinOverlay.jsx";

export default function App() {
  const chat = useChat();
  const [panel, setPanel] = useState(null);
  const opener = useRef(null);

  useEffect(() => {
    if (!panel) {
      opener.current?.focus();
      opener.current = null;
      return;
    }

    document.querySelector(`#${panel} [data-panel-close]`)?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") setPanel(null);
    };
    const onResize = () => {
      if (!opener.current?.getClientRects().length) setPanel(null);
    };
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, [panel]);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const style = document.documentElement.style;
    function updateViewport() {
      if (Math.abs(viewport.scale - 1) > 0.01) return;
      style.setProperty("--visible-height", `${viewport.height}px`);
      style.setProperty("--visible-top", `${viewport.offsetTop}px`);
    }
    updateViewport();
    viewport.addEventListener("resize", updateViewport);
    viewport.addEventListener("scroll", updateViewport);
    return () => {
      viewport.removeEventListener("resize", updateViewport);
      viewport.removeEventListener("scroll", updateViewport);
      style.removeProperty("--visible-height");
      style.removeProperty("--visible-top");
    };
  }, []);

  function openPanel(event) {
    opener.current = event.currentTarget;
    setPanel(event.currentTarget.getAttribute("aria-controls"));
  }

  const closePanel = () => setPanel(null);
  const transportOpen = panel === "transport-panel";
  const mobilePanelOpen = Boolean(panel) && !transportOpen;

  return (
    <>
      <IconSprite />
      <div className="ambient ambient-one" /><div className="ambient ambient-two" /><div className="ambient ambient-three" />
      <div className="app-shell" inert={!chat.state.joined || transportOpen}>
        <Sidebar state={chat.state} open={panel === "navigation-panel"} inert={panel === "assistant-panel"} onClose={closePanel} onJoinRoom={chat.joinRoom} onSelectDm={chat.selectDm} onSignOut={() => { closePanel(); chat.signOut(); }} />
        <Conversation key={chat.state.username.toLowerCase()} state={chat.state} inert={mobilePanelOpen} panel={panel} onSend={chat.sendMessage} onNotifyTyping={chat.notifyTyping} onEdit={chat.editMessage} onDelete={chat.deleteMessage} onReact={chat.toggleReaction} onMarkRead={chat.markRead} onUpload={chat.uploadAttachment} onLoadOlder={chat.loadOlder} onOpenPanel={openPanel} />
        <AiPanel state={chat.state} open={panel === "assistant-panel"} inert={panel === "navigation-panel"} onClose={closePanel} onSend={chat.sendAi} onSummarize={chat.summarizeRoom} onHistory={chat.showAiHistory} onReset={chat.resetAi} />
        {mobilePanelOpen ? <div className="mobile-backdrop" onClick={closePanel} /> : null}
      </div>
      <TransportDrawer open={transportOpen} events={chat.state.events} onClose={closePanel} onClear={chat.clearEvents} />
      <JoinOverlay state={chat.state} onJoin={chat.join} onAuthenticate={chat.authenticate} />
    </>
  );
}
