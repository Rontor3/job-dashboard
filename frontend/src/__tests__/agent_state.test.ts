import { test, expect } from "vitest";
import { encodeElementMessage } from "@jobdash/agent-protocol";
import { EMPTY, busyWith, exchangesFor, reduce, type Entry } from "../agent/state.ts";
import { captureContext } from "../agent/capture.ts";

const user = (id: number, text: string): Entry => ({ id, kind: "pi.user", model: [{ role: "user", content: text }] });
const said = (id: number, text: string): Entry =>
  ({ id, kind: "pi.assistant", model: [{ role: "assistant", content: [{ type: "text", text }] }] });

test("a snapshot then streamed text builds the thread, and entries never duplicate", () => {
  let s = reduce(EMPTY, { type: "snapshot", entries: [user(1, "hi")], run: { id: 1 }, inbox: [{ id: 4 }] });
  expect(s).toMatchObject({ running: true, inbox: [4] });
  s = reduce(s, { type: "message_start", message: { role: "assistant", content: [] } });
  s = reduce(s, { type: "message_update", changes: [{ type: "text_start", contentIndex: 0, block: { type: "text", text: "" } }] });
  s = reduce(s, { type: "message_update", changes: [{ type: "text_delta", contentIndex: 0, delta: "Hel" }, { type: "text_delta", contentIndex: 0, delta: "lo" }] });
  expect(s.partial?.content).toEqual([{ type: "text", text: "Hello" }]);
  s = reduce(s, { type: "message_end", entry: said(2, "Hello") });
  s = reduce(s, { type: "entry_appended", entry: said(2, "Hello") });
  expect(s.entries.map((e) => e.id)).toEqual([1, 2]);
  expect(s.partial).toBeNull();
  s = reduce(s, { type: "tool_execution_start", toolCallId: "a", toolName: "get_profile" });
  expect(s.toolsRunning).toEqual(["get_profile"]);
  s = reduce(s, { type: "tool_execution_end", toolCallId: "a", toolName: "get_profile" });
  s = reduce(s, { type: "run_end" });
  expect(s).toMatchObject({ running: false, toolsRunning: [] });
});

test("a popover sees only the exchanges started from its element", () => {
  const job = encodeElementMessage({ anchor: "job:4", text: "ML Eng" }, "Why this score?");
  const entries = [user(1, "general"), said(2, "ok"), user(3, job), said(4, "Because"), user(5, "other"), said(6, "x")];
  expect(exchangesFor(entries, "job:4").map((e) => e.id)).toEqual([3, 4]);
  expect(busyWith({ ...EMPTY, entries, running: true })).toBe("other");
  expect(busyWith({ ...EMPTY, entries })).toBeUndefined();
});

test("a click captures the anchored component, its heading and the tab", () => {
  document.body.innerHTML = `<article data-agent="qbank:notice"><h3>Notice period?</h3><span id="s">30 days</span></article>`;
  const ctx = captureContext(document.getElementById("s")!, "answers");
  expect(ctx).toMatchObject({ anchor: "qbank:notice", heading: "Notice period?", tab: "answers" });
  expect(ctx.text).toContain("30 days");
  document.body.innerHTML = `<p id="p">${"x".repeat(3000)}</p>`;
  const plain = captureContext(document.getElementById("p")!);
  expect(plain.anchor).toBeUndefined();
  expect(plain.text).toHaveLength(1500);
});
