import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyMessageDelete,
  applyMessageUpdate,
  applyReactionUpdate,
  dayLabel,
  mergeMessages,
} from "./messages.js";

const msg = (id) => ({ kind: "message", id, text: `m${id}` });
const note = (text) => ({ kind: "system", text });

test("history arriving before any stored message goes above system notes", () => {
  const merged = mergeMessages([note("Welcome")], [msg(1), msg(2)]);
  assert.deepEqual(merged.map((e) => e.text), ["m1", "m2", "Welcome"]);
});

test("duplicates are ignored and the same array is returned when nothing is new", () => {
  const existing = [msg(1), msg(2)];
  assert.equal(mergeMessages(existing, [msg(1), msg(2)]), existing);
});

test("older pages are prepended and newer missed messages are appended", () => {
  const existing = [msg(5), note("Reconnected"), msg(6)];
  const merged = mergeMessages(existing, [msg(7), msg(3), msg(4)]);
  assert.deepEqual(merged.map((e) => e.text), ["m3", "m4", "m5", "Reconnected", "m6", "m7"]);
});

test("gaps are filled in id order", () => {
  const merged = mergeMessages([msg(1), msg(4)], [msg(3), msg(2)]);
  assert.deepEqual(merged.map((e) => e.id), [1, 2, 3, 4]);
});

test("inputs are not mutated", () => {
  const existing = [msg(2)];
  const incoming = [msg(3), msg(1)];
  mergeMessages(existing, incoming);
  assert.deepEqual(existing.map((e) => e.id), [2]);
  assert.deepEqual(incoming.map((e) => e.id), [3, 1]);
});

test("applyMessageUpdate, applyMessageDelete, and applyReactionUpdate are immutable", () => {
  const list = [msg(1), msg(2)];
  const edited = applyMessageUpdate(list, { id: 2, text: "edited", edited_at: "2026-11-10T09:00:00Z" });
  assert.equal(edited[1].text, "edited");
  assert.equal(list[1].text, "m2");

  const reacted = applyReactionUpdate(edited, { id: 1, reactions: { "👍": ["alice"] } });
  assert.deepEqual(reacted[0].reactions, { "👍": ["alice"] });

  const afterDel = applyMessageDelete(reacted, { id: 1 });
  assert.deepEqual(afterDel.map((e) => e.id), [2]);
});

test("dayLabel names today and yesterday and ignores missing times", () => {
  const now = new Date(2026, 10, 10, 9, 0);
  assert.equal(dayLabel(new Date(2026, 10, 10, 0, 5).toISOString(), now), "TODAY");
  assert.equal(dayLabel(new Date(2026, 10, 9, 23, 55).toISOString(), now), "YESTERDAY");
  assert.notEqual(dayLabel(new Date(2026, 10, 1).toISOString(), now), "");
  assert.equal(dayLabel(undefined, now), "");
  assert.equal(dayLabel("not a date", now), "");
});
