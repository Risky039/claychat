// Pure helpers for chat message lists (no React), unit-tested with `node --test`.

export const ALLOWED_EMOJI = ["👍", "❤️", "😂", "🎉", "🚀", "👀", "🔥", "💡"];

// Insert stored messages by id. System notes (no id) keep their place relative to
// neighbouring messages; if nothing has an id yet, history goes before the notes.
export function mergeMessages(existing, incoming) {
  const known = new Set(existing.map((entry) => entry.id).filter((id) => id != null));
  const fresh = incoming.filter((message) => !known.has(message.id)).sort((a, b) => a.id - b.id);
  if (!fresh.length) return existing;
  if (known.size === 0) return [...fresh, ...existing];
  const result = [];
  let next = 0;
  for (const entry of existing) {
    while (entry.id != null && next < fresh.length && fresh[next].id < entry.id) result.push(fresh[next++]);
    result.push(entry);
  }
  return [...result, ...fresh.slice(next)];
}

export function applyMessageUpdate(entries, update) {
  if (!entries || !entries.length) return entries;
  let changed = false;
  const next = entries.map((entry) => {
    if (entry.id !== update.id) return entry;
    changed = true;
    return { ...entry, text: update.text, edited_at: update.edited_at };
  });
  return changed ? next : entries;
}

export function applyMessageDelete(entries, deletion) {
  if (!entries || !entries.length) return entries;
  const next = entries.filter((entry) => entry.id !== deletion.id);
  return next.length === entries.length ? entries : next;
}

export function applyReactionUpdate(entries, update) {
  if (!entries || !entries.length) return entries;
  let changed = false;
  const next = entries.map((entry) => {
    if (entry.id !== update.id) return entry;
    changed = true;
    return { ...entry, reactions: update.reactions || {} };
  });
  return changed ? next : entries;
}

export function dayLabel(value, now = new Date()) {
  const date = new Date(value);
  if (value == null || Number.isNaN(date.getTime())) return "";
  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86400000);
  if (days === 0) return "TODAY";
  if (days === 1) return "YESTERDAY";
  const options = { weekday: "short", day: "numeric", month: "short" };
  if (date.getFullYear() !== now.getFullYear()) options.year = "numeric";
  return date.toLocaleDateString(undefined, options).toUpperCase();
}
