import { useEffect, useState } from "react";
import { useChat } from "./useChat.js";
import { IconSprite } from "./components/Icons.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Conversation from "./components/Conversation.jsx";
import AiPanel from "./components/AiPanel.jsx";
import TransportDrawer from "./components/TransportDrawer.jsx";
import JoinOverlay from "./components/JoinOverlay.jsx";

export default function App() {
  const chat = useChat();
  const [mobilePanel, setMobilePanel] = useState(null);
  const [transportOpen, setTransportOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setMobilePanel(null);
        setTransportOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  function joinRoom(room) {
    chat.joinRoom(room);
    setMobilePanel(null);
  }

  function selectDm(name) {
    chat.selectDm(name);
    setMobilePanel(null);
  }

  return (
    <>
      <IconSprite />
      <div className="ambient ambient-one" /><div className="ambient ambient-two" /><div className="ambient ambient-three" />
      <div className="app-shell">
        <Sidebar state={chat.state} open={mobilePanel === "sidebar"} onClose={() => setMobilePanel(null)} onJoinRoom={joinRoom} onSelectDm={selectDm} onSignOut={chat.signOut} />
        <Conversation state={chat.state} onSend={chat.sendMessage} onNotifyTyping={chat.notifyTyping} onEdit={chat.editMessage} onDelete={chat.deleteMessage} onReact={chat.toggleReaction} onMarkRead={chat.markRead} onUpload={chat.uploadAttachment} onLoadOlder={chat.loadOlder} onOpenNav={() => setMobilePanel("sidebar")} onOpenAi={() => setMobilePanel("ai")} onOpenTransport={() => setTransportOpen(true)} />
        <AiPanel state={chat.state} open={mobilePanel === "ai"} onClose={() => setMobilePanel(null)} onSend={chat.sendAi} onSummarize={chat.summarizeRoom} onHistory={chat.showAiHistory} onReset={chat.resetAi} />
      </div>
      <TransportDrawer open={transportOpen} events={chat.state.events} onClose={() => setTransportOpen(false)} onClear={chat.clearEvents} />
      {mobilePanel ? <div className="mobile-backdrop" onClick={() => setMobilePanel(null)} /> : null}
      <JoinOverlay state={chat.state} onJoin={chat.join} onAuthenticate={chat.authenticate} />
    </>
  );
}
