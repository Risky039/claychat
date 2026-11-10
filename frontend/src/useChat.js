import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  applyMessageDelete,
  applyMessageUpdate,
  applyReactionUpdate,
  mergeMessages,
} from "./messages.js";

const initialState = {
  username: "",
  authenticated: false,
  inviteRequired: false,
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
  roomHasMore: {},
  roomLoadingOlder: {},
  dmHasMore: {},
  dmLoadingOlder: {},
  typingByChannel: {},
  readByMessage: {},
  users: [],
  aiMessages: [],
  aiPending: false,
  events: [],
};

const MAX_ENTRIES = 1000;

function appendTo(map, key, entry) {
  return { ...map, [key]: [...(map[key] || []), entry].slice(-MAX_ENTRIES) };
}

function hasMessage(entries, id) {
  return id != null && entries.some((entry) => entry.id === id);
}

function addSystem(state, text, room = state.currentRoom) {
  return { ...state, roomMessages: appendTo(state.roomMessages, room, { kind: "system", text, time: new Date().toISOString() }) };
}

function updateInAllChannels(map, fn) {
  let changed = false;
  const next = {};
  for (const [key, list] of Object.entries(map)) {
    const updated = fn(list);
    if (updated !== list) changed = true;
    next[key] = updated;
  }
  return changed ? next : map;
}

function reducer(state, action) {
  switch (action.type) {
    case "SESSION_INFO":
      return { ...state, inviteRequired: Boolean(action.inviteRequired) };
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
        roomLoadingOlder: {},
        dmLoadingOlder: {},
        typingByChannel: {},
        joinError: state.joinError || (state.joined ? "" : "Could not reach the chat server. Try again."),
      };
    case "JOIN_REJECTED":
      return { ...state, joined: false, registered: false, status: "offline", joinError: action.text };
    case "SIGNED_OUT":
      return { ...initialState, inviteRequired: state.inviteRequired };
    case "SEND":
      return { ...state, events: [...state.events, { direction: "out", item: action.item, time: new Date().toISOString() }].slice(-80) };
    case "CLEAR_EVENTS":
      return { ...state, events: [] };
    case "CLEAR_TYPING": {
      const current = state.typingByChannel[action.channel] || [];
      const filtered = current.filter((u) => u !== action.username);
      if (filtered.length === current.length) return state;
      return { ...state, typingByChannel: { ...state.typingByChannel, [action.channel]: filtered } };
    }
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
    case "HISTORY_REQUEST":
      return { ...state, roomLoadingOlder: { ...state.roomLoadingOlder, [action.room]: true } };
    case "DM_HISTORY_REQUEST":
      return { ...state, dmLoadingOlder: { ...state.dmLoadingOlder, [action.key]: true } };
    case "RECEIVE": {
      const item = action.item;
      let next = { ...state, events: [...state.events, { direction: "in", item, time: new Date().toISOString() }].slice(-80) };
      switch (item.type) {
        case "info":
          return next;
        case "welcome":
          next = {
            ...next,
            username: item.username || state.username,
            authenticated: Boolean(item.authenticated),
            registered: true,
            joined: true,
            status: "connected",
            joinError: "",
            users: [],
            aiMessages: state.joined ? [] : state.aiMessages,
            aiPending: false,
          };
          return addSystem(next, state.joined ? "Reconnected. Your private AI context starts fresh." : `Welcome, ${item.username || state.username}. You're in #lobby.`);
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
          if (hasMessage(next.roomMessages[item.room] || [], item.id)) return next;
          next.roomMessages = appendTo(next.roomMessages, item.room, { kind: "message", ...item });
          if (state.active.type !== "room" || state.active.id !== item.room) {
            next.roomUnread = { ...next.roomUnread, [item.room]: (state.roomUnread[item.room] || 0) + 1 };
          }
          return next;
        }
        case "history": {
          const incoming = (item.messages || []).map((message) => ({ kind: "message", ...message }));
          return {
            ...next,
            roomMessages: { ...next.roomMessages, [item.room]: mergeMessages(next.roomMessages[item.room] || [], incoming) },
            roomHasMore: { ...next.roomHasMore, [item.room]: Boolean(item.has_more) },
            roomLoadingOlder: { ...next.roomLoadingOlder, [item.room]: false },
          };
        }
        case "dm": {
          const other = item.username.toLowerCase() === state.username.toLowerCase() ? item.to : item.username;
          const key = other.toLowerCase();
          if (hasMessage(next.dmMessages[key] || [], item.id)) return next;
          next.dmMessages = appendTo(next.dmMessages, key, { kind: "message", ...item });
          if (state.active.type !== "dm" || state.active.id.toLowerCase() !== key) {
            next.dmUnread = { ...next.dmUnread, [key]: (state.dmUnread[key] || 0) + 1 };
          }
          return next;
        }
        case "dm_history": {
          const key = (item.with_user || "").toLowerCase();
          const incoming = (item.messages || []).map((message) => ({ kind: "message", ...message }));
          return {
            ...next,
            dmMessages: { ...next.dmMessages, [key]: mergeMessages(next.dmMessages[key] || [], incoming) },
            dmHasMore: { ...next.dmHasMore, [key]: Boolean(item.has_more) },
            dmLoadingOlder: { ...next.dmLoadingOlder, [key]: false },
          };
        }
        case "typing": {
          const channel = item.room ? `room:${item.room.toLowerCase()}` : `dm:${(item.username || "").toLowerCase()}`;
          const existing = next.typingByChannel[channel] || [];
          if (existing.includes(item.username)) return next;
          return {
            ...next,
            typingByChannel: { ...next.typingByChannel, [channel]: [...existing, item.username] },
          };
        }
        case "message_updated":
          return {
            ...next,
            roomMessages: updateInAllChannels(next.roomMessages, (list) => applyMessageUpdate(list, item)),
            dmMessages: updateInAllChannels(next.dmMessages, (list) => applyMessageUpdate(list, item)),
          };
        case "message_deleted":
          return {
            ...next,
            roomMessages: updateInAllChannels(next.roomMessages, (list) => applyMessageDelete(list, item)),
            dmMessages: updateInAllChannels(next.dmMessages, (list) => applyMessageDelete(list, item)),
          };
        case "reactions_updated":
          return {
            ...next,
            roomMessages: updateInAllChannels(next.roomMessages, (list) => applyReactionUpdate(list, item)),
            dmMessages: updateInAllChannels(next.dmMessages, (list) => applyReactionUpdate(list, item)),
          };
        case "read_receipt": {
          const readers = next.readByMessage[item.id] || [];
          if (readers.includes(item.username)) return next;
          return {
            ...next,
            readByMessage: { ...next.readByMessage, [item.id]: [...readers, item.username] },
          };
        }
        case "presence":
          return addSystem(next, `${item.username} ${item.action} the room.`);
        case "users":
          return { ...next, users: item.usernames || [] };
        case "ai_status":
          return { ...next, aiPending: item.state === "thinking" };
        case "ai_delta": {
          const list = [...next.aiMessages];
          const last = list[list.length - 1];
          if (last && last.role === "assistant" && last.request_id === item.request_id) {
            list[list.length - 1] = { ...last, content: (last.content || "") + (item.delta || "") };
          } else {
            list.push({ role: "assistant", content: item.delta || "", request_id: item.request_id, streaming: true });
          }
          return { ...next, aiMessages: list };
        }
        case "ai": {
          const list = [...next.aiMessages];
          const idx = item.request_id ? list.findIndex((m) => m.request_id === item.request_id) : -1;
          const entry = { role: "assistant", content: item.text, time: item.time, kind: item.kind, room: item.room };
          if (idx >= 0) list[idx] = entry;
          else list.push(entry);
          return { ...next, aiPending: false, aiMessages: list };
        }
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
  const typingTimersRef = useRef({});
  const lastTypingSentRef = useRef(0);
  const attemptsRef = useRef(0);
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
      if (socketRef.current !== socket || disposedRef.current) return;
      send({ type: "hello", username });
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
      if (item.type === "error" && !stateRef.current.registered) {
        if (stateRef.current.joined && item.text?.includes("already in use")) {
          socket.close();
          return;
        }
        allowReconnectRef.current = false;
        dispatch({ type: "JOIN_REJECTED", text: item.text });
        socket.close();
        return;
      }
      dispatch({ type: "RECEIVE", item });
      if (item.type === "typing") {
        const channel = item.room ? `room:${item.room.toLowerCase()}` : `dm:${(item.username || "").toLowerCase()}`;
        const timerKey = `${channel}:${item.username}`;
        clearTimeout(typingTimersRef.current[timerKey]);
        typingTimersRef.current[timerKey] = setTimeout(() => {
          dispatch({ type: "CLEAR_TYPING", channel, username: item.username });
        }, 4000);
      } else if (item.type === "welcome") {
        attemptsRef.current = 0;
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
        const delay = Math.min(15000, 1500 * Math.pow(1.6, attemptsRef.current++));
        timerRef.current = setTimeout(() => connect(stateRef.current.username), delay);
      }
    });
  }, [send]);

  useEffect(() => {
    disposedRef.current = false;
    fetch("/api/me", { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((info) => {
        if (!info || disposedRef.current) return;
        dispatch({ type: "SESSION_INFO", inviteRequired: info.invite_required });
        if (info.authenticated && info.username) {
          allowReconnectRef.current = true;
          dispatch({ type: "JOIN_ATTEMPT", username: info.username });
          connect(info.username);
        }
      })
      .catch(() => {});
    return () => {
      disposedRef.current = true;
      clearTimeout(timerRef.current);
      for (const timer of Object.values(typingTimersRef.current)) clearTimeout(timer);
      socketRef.current?.close();
    };
  }, [connect]);

  const join = useCallback((username) => {
    allowReconnectRef.current = true;
    attemptsRef.current = 0;
    dispatch({ type: "JOIN_ATTEMPT", username });
    window.localStorage.setItem("claychat-nickname", username);
    connect(username);
  }, [connect]);

  const authenticate = useCallback(async (mode, { username, password, inviteCode }) => {
    const endpoint = mode === "register" ? "/api/register" : "/api/login";
    dispatch({ type: "JOIN_ATTEMPT", username });
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password, invite_code: inviteCode || "" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        dispatch({ type: "JOIN_REJECTED", text: data.error || "Authentication failed" });
        return false;
      }
      allowReconnectRef.current = true;
      attemptsRef.current = 0;
      window.localStorage.setItem("claychat-nickname", data.username);
      connect(data.username);
      return true;
    } catch {
      dispatch({ type: "JOIN_REJECTED", text: "Could not reach the authentication server." });
      return false;
    }
  }, [connect]);

  const signOut = useCallback(async () => {
    allowReconnectRef.current = false;
    clearTimeout(timerRef.current);
    socketRef.current?.close();
    try {
      await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
    } catch {
      // ignore network error on logout
    }
    dispatch({ type: "SIGNED_OUT" });
  }, []);

  const joinRoom = useCallback((room) => {
    if (room === stateRef.current.currentRoom) dispatch({ type: "SELECT_ROOM", room });
    else send({ type: "join", room });
  }, [send]);

  const selectDm = useCallback((name) => {
    dispatch({ type: "SELECT_DM", name });
    const current = stateRef.current;
    const key = name.toLowerCase();
    if (current.authenticated && !(current.dmMessages[key] || []).length) {
      send({ type: "dm_history", with_user: name });
    }
  }, [send]);

  const loadOlder = useCallback((target) => {
    const current = stateRef.current;
    if (current.active.type === "dm") {
      const key = target.toLowerCase();
      const oldest = (current.dmMessages[key] || []).find((entry) => entry.id != null);
      if (!oldest || current.dmLoadingOlder[key] || !current.dmHasMore[key]) return;
      if (send({ type: "dm_history", with_user: target, before: oldest.id })) {
        dispatch({ type: "DM_HISTORY_REQUEST", key });
      }
      return;
    }
    const oldest = (current.roomMessages[target] || []).find((entry) => entry.id != null);
    if (!oldest || current.roomLoadingOlder[target] || !current.roomHasMore[target]) return;
    if (send({ type: "history", room: target, before: oldest.id })) dispatch({ type: "HISTORY_REQUEST", room: target });
  }, [send]);

  const sendMessage = useCallback((text, attachmentId = null) => {
    const active = stateRef.current.active;
    const payload = active.type === "room" ? { type: "message", text } : { type: "dm", to: active.id, text };
    if (attachmentId) payload.attachment_id = attachmentId;
    return send(payload);
  }, [send]);

  const notifyTyping = useCallback(() => {
    const now = Date.now();
    if (now - lastTypingSentRef.current < 1500) return;
    lastTypingSentRef.current = now;
    const active = stateRef.current.active;
    send(active.type === "room" ? { type: "typing" } : { type: "typing", to: active.id });
  }, [send]);

  const editMessage = useCallback((id, text) => send({ type: "edit", id, text }), [send]);
  const deleteMessage = useCallback((id) => send({ type: "delete", id }), [send]);
  const toggleReaction = useCallback((id, emoji) => send({ type: "react", id, emoji }), [send]);
  const markRead = useCallback((id) => send({ type: "read", id }), [send]);

  const uploadAttachment = useCallback(async (file) => {
    const form = new FormData();
    form.append("file", file, file.name);
    const res = await fetch("/api/uploads", {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Upload failed");
    return data;
  }, []);

  const sendAi = useCallback((text) => {
    if (stateRef.current.aiPending) return false;
    if (!send({ type: "ai", text, stream: true })) return false;
    dispatch({ type: "AI_PROMPT", text });
    return true;
  }, [send]);

  const summarizeRoom = useCallback((count = 30) => {
    if (stateRef.current.aiPending) return false;
    const room = stateRef.current.currentRoom;
    if (!send({ type: "summarize", room, count })) return false;
    dispatch({ type: "AI_PROMPT", text: `Summarize #${room}` });
    return true;
  }, [send]);

  return {
    state,
    join,
    authenticate,
    signOut,
    joinRoom,
    selectDm,
    loadOlder,
    sendMessage,
    notifyTyping,
    editMessage,
    deleteMessage,
    toggleReaction,
    markRead,
    uploadAttachment,
    sendAi,
    summarizeRoom,
    showAiHistory: () => send({ type: "ai_history" }),
    resetAi: () => send({ type: "ai_reset" }),
    clearEvents: () => dispatch({ type: "CLEAR_EVENTS" }),
  };
}
