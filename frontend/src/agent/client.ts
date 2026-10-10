// Calls from the dashboard to the agent service (/agent/*) and the human-only api routes the agent's widgets use.
// Secret values and the résumé go from here straight to FastAPI; they never pass through the agent.
import type { ElementContext, SessionsState } from "@jobdash/agent-protocol";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // keep the status
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const post = (url: string, body?: unknown, headers: Record<string, string> = {}) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body ?? {}),
  });

export const fetchSessions = () => fetch("/agent/sessions").then((r) => json<SessionsState>(r));
export const newSession = () => post("/agent/sessions").then((r) => json<SessionsState & { id: string }>(r));
export const activateSession = (id: string) => post(`/agent/sessions/${id}/activate`).then((r) => json<SessionsState>(r));
export const stopSession = (id: string) => post(`/agent/sessions/${id}/stop`).then((r) => json<{ stopped: boolean }>(r));

export function sendMessage(session: string, content: string, context?: ElementContext) {
  const requestId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return post(`/agent/sessions/${session}/messages`, { content, requestId, context }).then((r) => json<{ submission: number }>(r));
}

export const undoChange = (id: number) => post(`/api/changes/${id}/undo`).then((r) => json<{ ok: boolean }>(r));

export interface Confirmation {
  id: number;
  method: string;
  path: string;
  body: unknown;
  summary: string;
  status: "pending" | "confirmed" | "cancelled" | "used";
}

export const fetchConfirmation = (session: string, id: number) =>
  fetch(`/api/confirmations?session_id=${encodeURIComponent(session)}`)
    .then((r) => json<{ confirmations: Confirmation[] }>(r))
    .then((d) => d.confirmations.find((c) => c.id === id));

/**
 * The human pressed Confirm: get the single-use token, then run the exact request the agent proposed, on behalf of
 * its session. Returns the response status and body for the agent to hear about.
 */
export async function confirmAction(session: string, c: Confirmation): Promise<{ status: number; detail: string }> {
  const { token } = await post(`/api/confirmations/${c.id}/confirm`).then((r) => json<{ token: string }>(r));
  const res = await fetch(c.path, {
    method: c.method,
    headers: {
      "X-Agent-Session": session, "X-Agent-Message": `confirm-${c.id}`, "X-Confirm-Token": token,
      ...(c.body == null ? {} : { "Content-Type": "application/json" }),
    },
    body: c.body == null ? undefined : JSON.stringify(c.body),
  });
  const text = await res.text();
  return { status: res.status, detail: text.slice(0, 300) };
}

export const cancelAction = (id: number) => post(`/api/confirmations/${id}/cancel`).then((r) => json<unknown>(r));

export const putSecret = (key: string, value: string) =>
  fetch(`/api/secrets/${key}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
  }).then((r) => json<{ set: boolean }>(r));

export const secretsPresent = () => fetch("/api/secrets").then((r) => json<{ secrets: Record<string, boolean> }>(r));

export const uploadResume = (file: Blob) =>
  fetch("/api/current-resume", { method: "PUT", headers: { "Content-Type": "application/pdf" }, body: file })
    .then((r) => json<{ uploaded: boolean; bytes: number }>(r));

export const fetchSetupState = () =>
  fetch("/api/setup-state").then((r) => json<{ exists: boolean; status: string | null }>(r));

export interface ChangeRow {
  id: number;
  at: string;
  actor: "agent" | "ui";
  session_id: string | null;
  entity: string;
  entity_id: string | null;
  field: string | null;
  before: unknown;
  after: unknown;
  undoable: boolean;
  undone_at: string | null;
  undo_of: number | null;
}

export const fetchChanges = (beforeId?: number) =>
  fetch(`/api/changes?limit=50${beforeId ? `&before_id=${beforeId}` : ""}`).then((r) => json<{ changes: ChangeRow[] }>(r));
