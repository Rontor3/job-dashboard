// The agent's only way to the user's data: HTTP to FastAPI, which validates, logs every change for Undo, gates
// consequential actions behind the human's Confirm, and never returns secret values.
import type { ChangeSummary } from "@jobdash/agent-protocol";

export interface CallOptions {
  body?: unknown;
  session: string;
  message: string;
  confirmToken?: string;
}

export interface ApiResult {
  status: number;
  ok: boolean;
  data: unknown;
  changes: ChangeSummary[];
}

export type Fetch = typeof fetch;

export interface ApiClient {
  readonly baseUrl: string;
  call(method: string, path: string, options: CallOptions): Promise<ApiResult>;
  /** A plain read without agent headers, for the service's own needs (config). */
  get(path: string): Promise<unknown>;
}

export function apiClient(baseUrl: string, fetchImpl: Fetch = fetch): ApiClient {
  const base = baseUrl.replace(/\/$/, "");
  return {
    baseUrl: base,
    async call(method, path, { body, session, message, confirmToken }) {
      const headers: Record<string, string> = { "x-agent-session": session, "x-agent-message": message };
      if (body !== undefined) headers["content-type"] = "application/json";
      if (confirmToken) headers["x-confirm-token"] = confirmToken;
      const res = await fetchImpl(base + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await res.text();
      let data: unknown = text;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        // not JSON: keep the text
      }
      let changes: ChangeSummary[] = [];
      try {
        changes = JSON.parse(res.headers.get("x-changes") ?? "[]");
      } catch {
        // malformed header: no chips
      }
      return { status: res.status, ok: res.ok, data, changes };
    },
    async get(path) {
      const res = await fetchImpl(base + path);
      if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
      return res.json();
    },
  };
}
