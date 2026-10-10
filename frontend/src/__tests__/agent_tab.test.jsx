import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import { AgentProvider } from "../agent/AgentProvider.tsx";
import AgentTab, { exportText } from "../agent/AgentTab.tsx";
import Markdown, { blocks } from "../agent/Markdown.tsx";
import { Thread } from "../agent/Thread.tsx";

let calls;
const COMMANDS = [
  { name: "model", description: "Select a model", kind: "builtin" },
  { name: "thinking", description: "Set the thinking level", kind: "builtin" },
  { name: "name", description: "Set the session display name", kind: "builtin" },
  { name: "tailor", description: "Tailor for a job", kind: "template" },
];
const STATS = { id: "s1", title: "Setup", createdAt: 0, conversation: 1, model: "qwen", thinkingLevel: "medium", contextWindow: 100000,
  contextTokens: 25000, entries: 0, messages: { user: 0, assistant: 0, toolCalls: 0, toolResults: 0 },
  usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0, cost: 0 }, tools: ["get_profile"], prompt: [{ file: "/r/docs/agent/system.md", loaded: true }] };

beforeEach(() => {
  calls = [];
  try { localStorage.clear(); } catch { /* none */ }
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    calls.push({ u, method: opts.method || "GET", body });
    const reply = u === "/agent/sessions" ? { id: "s1", active: "s1", items: [{ id: "s1", title: "Setup", createdAt: 0 }] }
      : u === "/agent/commands" ? { commands: COMMANDS }
      : u.endsWith("/stats") ? STATS
      : u.endsWith("/command") ? { ok: true, message: `ran ${body.name}` }
      : { ok: true, submission: 7 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(reply) });
  });
});

const renderTab = async () => {
  render(<AgentProvider><AgentTab /></AgentProvider>);
  await screen.findByText(/25\.0%\/100k/);                                   // footer: context from /stats
  return screen.getByLabelText("Message the agent");
};

test("Enter steers, Alt+Enter queues a follow-up", async () => {
  const box = await renderTab();
  fireEvent.change(box, { target: { value: "hello" } });
  fireEvent.keyDown(box, { key: "Enter" });
  fireEvent.change(box, { target: { value: "after that" } });
  fireEvent.keyDown(box, { key: "Enter", altKey: true });
  await waitFor(() => expect(calls.filter((c) => c.u.endsWith("/messages")).map((c) => [c.body.content, c.body.whenBusy]))
    .toEqual([["hello", "steer"], ["after that", "followUp"]]));
});

test("/ opens the command menu; Tab completes; a server command runs with its arguments", async () => {
  const box = await renderTab();
  fireEvent.change(box, { target: { value: "/th" } });
  expect(screen.getByRole("listbox", { name: "Commands" })).toHaveTextContent("/thinking");
  fireEvent.keyDown(box, { key: "Tab" });
  expect(box.value).toBe("/thinking ");
  fireEvent.change(box, { target: { value: "/thinking high" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => expect(calls.find((c) => c.u.endsWith("/command")).body).toMatchObject({ name: "thinking", args: "high" }));
  expect(await screen.findByText("ran thinking")).toBeInTheDocument();
});

test("templates are listed as prompts, and Up brings back the last prompt", async () => {
  const box = await renderTab();
  fireEvent.change(box, { target: { value: "/" } });
  expect(screen.getByRole("listbox")).toHaveTextContent("[prompt] Tailor for a job");
  fireEvent.change(box, { target: { value: "first prompt" } });
  fireEvent.keyDown(box, { key: "Enter" });
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box.value).toBe("first prompt");
});

test("/hotkeys and /session open panels without calling the agent", async () => {
  const box = await renderTab();
  fireEvent.change(box, { target: { value: "/hotkeys" } });
  fireEvent.keyDown(box, { key: "Escape" });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByRole("dialog", { name: "/hotkeys" })).toHaveTextContent("Alt+Enter");
  expect(calls.some((c) => c.u.endsWith("/command"))).toBe(false);
});

const toolTurn = [
  { id: 1, kind: "pi.user", model: [{ role: "user", content: "set my city" }] },
  { id: 2, kind: "pi.assistant", model: [{ role: "assistant", content: [
    { type: "thinking", thinking: "they want Pune" },
    { type: "toolCall", id: "c1", name: "update_profile", arguments: { fields: { location: "Pune" } } },
  ] }] },
  { id: 3, kind: "pi.tool-result", model: [{ role: "toolResult", toolCallId: "c1", toolName: "update_profile",
    content: [{ type: "text", text: Array.from({ length: 10 }, (_, i) => `line ${i}`).join("\n") }],
    details: { changes: [{ id: 9, entity: "profile", entity_id: "1", field: "location", before: null, after: "Pune", undoable: true }] } }] },
  { id: 4, kind: "pi.assistant", model: [{ role: "assistant", content: [{ type: "text", text: "Set **location** to `Pune`." }] }] },
];

test("a tool call shows its name, args, collapsed output, change line; thinking is folded until shown", () => {
  const { rerender } = render(<Thread entries={toolTurn} partial={null} running={false} />);
  expect(screen.getByText("update_profile")).toBeInTheDocument();
  expect(screen.getByText(/fields=\{"location":"Pune"\}/)).toBeInTheDocument();
  expect(screen.getByText(/4 more lines/)).toBeInTheDocument();
  expect(screen.getByText(/Changed Profile location: — → Pune/)).toBeInTheDocument();
  expect(screen.queryByText("they want Pune")).toBeNull();
  rerender(<Thread entries={toolTurn} partial={null} running={false} view={{ expandTools: true, showThinking: true }} />);
  expect(screen.getByText("they want Pune")).toBeInTheDocument();
  expect(screen.getByText(/line 9/)).toBeInTheDocument();
  expect(screen.getByText("Pune", { selector: "code" })).toBeInTheDocument();
});

test("markdown renders as elements, never as raw HTML", () => {
  const { container } = render(<Markdown text={"# Title\n\n- **a**\n- b\n\n<img src=x onerror=alert(1)>\n\n```\ncode\n```"} />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelectorAll("li")).toHaveLength(2);
  expect(container.querySelector("pre code").textContent).toBe("code");
  expect(blocks("a\nb\n\nc").map((b) => b.kind)).toEqual(["p", "p"]);
});

test("/export as markdown has the prompts, answers and tool calls", () => {
  const md = exportText(toolTurn, "Setup", "md");
  expect(md).toContain("# Setup");
  expect(md).toContain("set my city");
  expect(md).toContain("> tool `update_profile`");
  expect(md).toContain("Set **location** to `Pune`.");
  expect(exportText(toolTurn, "x", "jsonl").trim().split("\n")).toHaveLength(4);
});

test("a mission starts a new session as its profile and hands it the task", async () => {
  await renderTab();
  fireEvent.click(screen.getAllByRole("button", { name: /Find my next jobs/ })[0]);
  await waitFor(() => expect(calls.some((c) => c.u === "/agent/sessions" && c.method === "POST" && c.body?.profile === "scout")).toBe(true));
  await waitFor(() => expect(calls.some((c) => c.u === "/agent/sessions/s1/messages" && /shortlist/.test(c.body.content))).toBe(true));
});
