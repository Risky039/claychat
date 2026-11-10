import { useCallback, useEffect, useReducer, useRef } from "react";

const initialState = {
  username: "",
  status: "offline",
  registered: false,
  joined: false,
  joinError: "",
  currentRoom: "lobby",
  active: { type: "room", id: "lobby" },
  rooms: ["lobby", "study", "lounge"],
  roomMessages: {},
  dmMessages: {},
  roomUnread: {},
  dmUnread: {},
  users: [],
  aiMessages: [],
  aiPending: false,
  events: [],
};

function appendTo(map, key, entry) {
  return { ...map, [key]: [...(map[key] || []), entry].slice(-200) };
}

function addSystem(state, text, room = state.currentRoom) {
  return { ...state, roomMessages: appendTo(state.roomMessages, room, { kind: "system", text }) };
}

function reducer(state, action) {
  switch (action.type) {
    case "JOIN_ATTEMPT":
      return { ...state, username: action.username, status: "connecting", joinError: "" };
    case "CONNECTING":
      return { ...state, status: "connecting" };
    case "DISCONNECTED":
      return {
        ...state,
        status: state.joined ? "reconnecting" : "offline",
        registered: false,
        users: [],
        joinError: state.joinError || (state.joined ? "" : "Could not reach the chat server. Try again."),
      };
    case "JOIN_REJECTED":
      return { ...state, joined: false, registered: false, status: "offline", joinError: action.text };
    case "SEND":
      return { ...state, events: [...state.events, { direction: "out", item: action.item, time: new Date().toISOString() }].slice(-80) };
    case "CLEAR_EVENTS":
      return { ...state, events: [] };
    case "SELECT_ROOM": {
      const unread = { ...state.roomUnread };
      delete unread[action.room];
      return { ...state, active: { type: "room", id: action.room }, roomUnread: unread };
    }
    case "SELECT_DM": {
      const unread = { ...state.dmUnread };
      delete unread[action.name.toLowerCase()];
      return { ...state, active: { type: "dm", id: action.name }, dmUnread: unread };
    }
    case "AI_PROMPT":
      return { ...state, aiPending: true, aiMessages: [...state.aiMessages, { role: "user", content: action.text, time: new Date().toISOString() }] };
    case "RECEIVE": {
      const item = action.item;
      let next = { ...state, events: [...state.events, { direction: "in", item, time: new Date().toISOString() }].slice(-80) };
      switch (item.type) {
        case "info":
          return next;
        case "welcome":
          next = {
            ...next,
            registered: true,
            joined: true,
            status: "connected",
            joinError: "",
            users: [],
            aiMessages: state.joined ? [] : state.aiMessages,
            aiPending: false,
          };
          return addSystem(next, state.joined ? "Reconnected. Your private AI context starts fresh." : `Welcome, ${state.username}. You're in #lobby.`);
        case "joined": {
          const unread = { ...next.roomUnread };
          delete unread[item.room];
          next = {
            ...next,
            currentRoom: item.room,
            active: { type: "room", id: item.room },
            rooms: next.rooms.includes(item.room) ? next.rooms : [...next.rooms, item.room],
            users: [],
            roomUnread: unread,
          };
          return addSystem(next, `You joined #${item.room}.`, item.room);
        }
        case "message": {
          next.roomMessages = appendTo(next.roomMessages, item.room, { kind: "message", ...item });
          if (state.active.type !== "room" || state.active.id !== item.room) {
            next.roomUnread = { ...state.roomUnread, [item.room]: (state.roomUnread[item.room] || 0) + 1 };
          }
          return next;
        }
        case "dm": {
          const other = item.username.toLowerCase() === state.username.toLowerCase() ? item.to : item.username;
          const key = other.toLowerCase();
          next.dmMessages = appendTo(next.dmMessages, key, { kind: "message", ...item });
          if (state.active.type !== "dm" || state.active.id.toLowerCase() !== key) {
            next.dmUnread = { ...state.dmUnread, [key]: (state.dmUnread[key] || 0) + 1 };
          }
          return next;
        }
        case "presence":
          return addSystem(next, `${item.username} ${item.action} the room.`);
        case "users":
          return { ...next, users: item.usernames || [] };
        case "ai_status":
          return { ...next, aiPending: item.state === "thinking" };
        case "ai":
          return { ...next, aiPending: false, aiMessages: [...next.aiMessages, { role: "assistant", content: item.text, time: item.time }] };
        case "ai_history":
          return { ...next, aiMessages: (item.messages || []).map((entry) => ({ ...entry })) };
        case "ai_reset":
          return { ...next, aiMessages: [], aiPending: false };
        case "error":
          if (item.source === "ai") {
            return { ...next, aiPending: false, aiMessages: [...next.aiMessages, { role: "error", content: item.text, time: item.time }] };
          }
          if (!state.registered) return { ...next, joinError: item.text };
          return addSystem(next, item.text);
        default:
          return next;
      }
    }
    default:
      return state;
  }
}

export function useChat() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  const socketRef = useRef(null);
  const timerRef = useRef(null);
  const disposedRef = useRef(false);
  const allowReconnectRef = useRef(true);
  stateRef.current = state;

  const send = useCallback((item) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(item));
    dispatch({ type: "SEND", item });
    return true;
  }, []);

  const connect = useCallback((username) => {
    clearTimeout(timerRef.current);
    if (socketRef.current) socketRef.current.close();
    dispatch({ type: "CONNECTING" });
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    socketRef.current = socket;

    socket.addEventListener("open", () => {
      if (socketRef.current === socket && !disposedRef.current) send({ type: "hello", username });
    });

    socket.addEventListener("message", (event) => {
      if (socketRef.current !== socket || disposedRef.current) return;
      let item;
      try {
        item = JSON.parse(event.data);
      } catch {
        dispatch({ type: "RECEIVE", item: { type: "error", text: "The server sent an unreadable message." } });
        return;
      }
      if (item.type === "error" && !stateRef.current.registered && item.text?.includes("already in use")) {
        allowReconnectRef.current = false;
        dispatch({ type: "JOIN_REJECTED", text: item.text });
        socket.close();
        return;
      }
      dispatch({ type: "RECEIVE", item });
      if (item.type === "welcome") {
        if (stateRef.current.currentRoom !== item.room) send({ type: "join", room: stateRef.current.currentRoom });
        else send({ type: "users" });
      } else if (item.type === "joined" || item.type === "presence") {
        send({ type: "users" });
      }
    });

    socket.addEventListener("close", () => {
      if (socketRef.current !== socket || disposedRef.current) return;
      dispatch({ type: "DISCONNECTED" });
      if (allowReconnectRef.current && stateRef.current.joined) {
        timerRef.current = setTimeout(() => connect(stateRef.current.username), 3000);
      }
    });
  }, [send]);

  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  const join = useCallback((username) => {
    allowReconnectRef.current = true;
    dispatch({ type: "JOIN_ATTEMPT", username });
    window.localStorage.setItem("claychat-nickname", username);
    connect(username);
  }, [connect]);

  const joinRoom = useCallback((room) => {
    if (room === stateRef.current.currentRoom) dispatch({ type: "SELECT_ROOM", room });
    else send({ type: "join", room });
  }, [send]);

  const selectDm = useCallback((name) => dispatch({ type: "SELECT_DM", name }), []);

  const sendMessage = useCallback((text) => {
    const active = stateRef.current.active;
    return active.type === "room" ? send({ type: "message", text }) : send({ type: "dm", to: active.id, text });
  }, [send]);

  const sendAi = useCallback((text) => {
    if (stateRef.current.aiPending) return false;
    if (!send({ type: "ai", text })) return false;
    dispatch({ type: "AI_PROMPT", text });
    return true;
  }, [send]);

  return {
    state,
    join,
    joinRoom,
    selectDm,
    sendMessage,
    sendAi,
    showAiHistory: () => send({ type: "ai_history" }),
    resetAi: () => send({ type: "ai_reset" }),
    clearEvents: () => dispatch({ type: "CLEAR_EVENTS" }),
  };
}
