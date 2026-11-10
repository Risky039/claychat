import React from "react";

export function Icon({ name, className = "" }) {
  return <svg className={className} aria-hidden="true"><use href={`#i-${name}`} /></svg>;
}

export function IconSprite() {
  return (
    <svg className="icon-sprite" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <symbol id="i-chat" viewBox="0 0 24 24"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5 8 8 0 0 1-3.2-.7L4 20l1.7-5.2A7.5 7.5 0 1 1 20 11.5Z"/><path d="M8.3 11.5h.1m4.1 0h.1m4.1 0h.1" strokeLinecap="round" strokeWidth="2.6"/></symbol>
      <symbol id="i-hash" viewBox="0 0 24 24"><path d="M9 3 6.5 21M17.5 3 15 21M4 9h17M3 16h17"/></symbol>
      <symbol id="i-spark" viewBox="0 0 24 24"><path d="m12 2 2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2L12 2Z"/><path d="M19 2v4M17 4h4"/></symbol>
      <symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3 19v-1a6 6 0 0 1 12 0v1H3ZM17 5a3 3 0 0 1 0 6M16 14a5 5 0 0 1 5 5h-3"/></symbol>
      <symbol id="i-send" viewBox="0 0 24 24"><path d="m21 3-7.5 18-3.2-7.3L3 10.5 21 3ZM10.3 13.7 21 3"/></symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
      <symbol id="i-code" viewBox="0 0 24 24"><path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-16-2 20"/></symbol>
      <symbol id="i-close" viewBox="0 0 24 24"><path d="M5 5 19 19M19 5 5 19"/></symbol>
      <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></symbol>
      <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0 .1 3M20 4v7h-7"/></symbol>
      <symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
    </svg>
  );
}

const palette = ["#e4dcf6", "#f6e0e4", "#deefe7", "#f8e8d5", "#dce7f8"];

export function Avatar({ name, className = "avatar" }) {
  const index = [...(name || "")].reduce((sum, letter) => sum + letter.charCodeAt(0), 0) % palette.length;
  return <span className={className} style={{ background: palette[index] }}>{(name || "?").slice(0, 2).toUpperCase()}</span>;
}

const formatter = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

export function shortTime(value) {
  const date = value ? new Date(value) : new Date();
  return Number.isNaN(date.getTime()) ? "now" : formatter.format(date);
}
