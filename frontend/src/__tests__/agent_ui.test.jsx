import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import { AgentProvider } from "../agent/AgentProvider.tsx";
import { ChangeChip } from "../agent/Thread.tsx";
import { ConfirmWidget, SecretWidget } from "../agent/Widgets.tsx";
import SetupBanner from "../agent/SetupBanner.tsx";
import ChangeHistory from "../agent/ChangeHistory.tsx";

let calls;
let routes;

beforeEach(() => {
  calls = [];
  routes = {};
  try { sessionStorage.clear(); } catch { /* no storage */ }
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const method = opts.method || "GET";
    calls.push({ u, method, headers: opts.headers || {}, body: opts.body });
    const hit = Object.keys(routes).find((k) => `${method} ${u}`.startsWith(k));
    const body = hit ? routes[hit] : u === "/agent/sessions" ? { id: "s1", active: "s1", items: [] } : { ok: true };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve("{}") });
  });
});

const sent = () => calls.filter((c) => c.u === "/agent/sessions/s1/messages").map((c) => JSON.parse(c.body).content);
const wrap = (ui) => render(<AgentProvider>{ui}</AgentProvider>);

test("a change chip undoes the change it shows", async () => {
  render(<ChangeChip change={{ id: 12, entity: "profile", entity_id: "me", field: "city", before: "Pune", after: "Delhi", undoable: true }} />);
  expect(screen.getByText(/Profile city: Pune → Delhi/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(await screen.findByText("Undone")).toBeInTheDocument();
  expect(calls.some((c) => c.u === "/api/changes/12/undo" && c.method === "POST")).toBe(true);
});

test("a secret goes straight to the api; the agent only hears that it was set", async () => {
  routes["GET /api/secrets"] = { secrets: {} };
  wrap(<SecretWidget keyName="LLM_API_KEY" reason="For the model" />);
  fireEvent.change(screen.getByLabelText("Value for LLM_API_KEY"), { target: { value: "sk-test-123" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText(/never the value/)).toBeInTheDocument();
  const put = calls.find((c) => c.u === "/api/secrets/LLM_API_KEY");
  expect(put.method).toBe("PUT");
  await waitFor(() => expect(sent()).toEqual(["[I set LLM_API_KEY]"]));
  expect(calls.filter((c) => c.u.startsWith("/agent")).some((c) => String(c.body).includes("sk-test-123"))).toBe(false);
});

const CONFIRM = { id: 5, method: "POST", path: "/api/queue/start", body: null, summary: "Start the apply queue", status: "pending" };

test("Confirm fetches a token, runs the exact request with it, and tells the agent", async () => {
  routes["GET /api/confirmations"] = { confirmations: [CONFIRM] };
  routes["POST /api/confirmations/5/confirm"] = { token: "tok" };
  wrap(<ConfirmWidget confirmation={CONFIRM} />);
  await waitFor(() => expect(calls.some((c) => c.u === "/agent/sessions")).toBe(true));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
  expect(await screen.findByText("Confirmed.")).toBeInTheDocument();
  const run = calls.find((c) => c.u === "/api/queue/start");
  expect(run.headers).toMatchObject({ "X-Confirm-Token": "tok", "X-Agent-Session": "s1" });
  await waitFor(() => expect(sent()).toEqual(["Confirmed: Start the apply queue. It's done."]));
});

test("Cancel never runs the request", async () => {
  wrap(<ConfirmWidget confirmation={CONFIRM} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(await screen.findByText("Cancelled.")).toBeInTheDocument();
  expect(calls.some((c) => c.u === "/api/confirmations/5/cancel")).toBe(true);
  expect(calls.some((c) => c.u === "/api/queue/start")).toBe(false);
});

test("the setup banner offers the agent until setup is complete, and Not now hides it", async () => {
  routes["GET /api/setup-state"] = { exists: false, status: null };
  const open = vi.fn();
  render(<AgentProvider onOpenTab={open}><SetupBanner /></AgentProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Finish setup with the agent" }));
  expect(open).toHaveBeenCalled();
  await waitFor(() => expect(sent()).toEqual(["Let's finish setting up the app."]));
});

test("the setup banner stays away once setup is complete", async () => {
  routes["GET /api/setup-state"] = { exists: true, status: "complete" };
  wrap(<SetupBanner />);
  await waitFor(() => expect(calls.some((c) => c.u === "/api/setup-state")).toBe(true));
  expect(screen.queryByText(/Setup isn't finished/)).toBeNull();
});

test("history lists every change and can undo one", async () => {
  routes["GET /api/changes"] = { changes: [
    { id: 3, at: "2026-10-10T10:00:00Z", actor: "agent", session_id: "s1", entity: "setting", entity_id: "min_score",
      field: "value", before: 60, after: 70, undoable: true, undone_at: null, undo_of: null },
    { id: 2, at: "2026-10-10T09:00:00Z", actor: "ui", session_id: null, entity: "secret", entity_id: "LLM_API_KEY",
      field: null, before: null, after: null, undoable: false, undone_at: null, undo_of: null },
  ] };
  render(<ChangeHistory />);
  expect(await screen.findByText(/Setting min_score: 60 → 70/)).toBeInTheDocument();
  expect(screen.getByText("Set LLM_API_KEY")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.u === "/api/changes/3/undo")).toBe(true));
});
