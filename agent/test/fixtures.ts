// Shared test setup: a real FastAPI (tests/agent_api_app.py) on a temp data root inside data/tmp, and a harness on
// a temp SQLite store driven by pi-ai's scripted faux model. Nothing calls a real model or touches the user's data.
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels, fauxProvider } from "@earendil-works/pi-ai";
import { createRegistry, defineExtension, Harness, type Extension } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { apiClient, type ApiClient } from "../src/api.ts";
import { createAgentApp } from "../src/app.ts";
import { REPO_ROOT } from "../src/env.ts";
import type { ModelSource } from "../src/model.ts";
import { sections } from "../src/prompt.ts";
import { makeTools } from "../src/tools.ts";

export const ctx = BACKGROUND_CONTEXT;
export const PYTHON = join(REPO_ROOT, ".venv", "bin", "python");
export const hasPython = existsSync(PYTHON);

export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.listen(0, "127.0.0.1", () => {
      const port = (s.address() as { port: number }).port;
      s.close(() => resolve(port));
    });
    s.on("error", reject);
  });
}

export interface Api {
  url: string;
  dir: string;
  client: ApiClient;
  stop(): void;
  /** A request as the human's browser makes it: no agent headers. */
  ui(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<any>;
}

/** `extraEnv` is applied after the LLM_* variables are cleared (the live eval passes the real model's settings). */
export async function startApi(extraEnv: Record<string, string> = {}): Promise<Api> {
  mkdirSync(join(REPO_ROOT, "data", "tmp"), { recursive: true });
  const dir = mkdtempSync(join(REPO_ROOT, "data", "tmp", "agent-test-"));
  const port = await freePort();
  const env: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: "src:.", JOB_DASHBOARD_DATA_DIR: dir, JOB_DASHBOARD_ENV_FILE: join(dir, ".env") };
  for (const k of Object.keys(env)) if (k.startsWith("LLM_")) delete env[k];
  Object.assign(env, extraEnv);
  const proc: ChildProcess = spawn(PYTHON, ["-m", "uvicorn", "tests.agent_api_app:app", "--port", String(port), "--log-level", "warning"],
    { cwd: REPO_ROOT, env, stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  proc.stderr!.on("data", (d) => (stderr += d));
  const url = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 20_000;
  for (;;) {
    if (proc.exitCode !== null) throw new Error(`api exited: ${stderr}`);
    try {
      if ((await fetch(`${url}/api/health`)).ok) break;
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) throw new Error(`api didn't start: ${stderr}`);
    await new Promise((r) => setTimeout(r, 100));
  }
  return {
    url, dir, client: apiClient(url),
    stop() {
      proc.kill();
      rmSync(dir, { recursive: true, force: true });
    },
    async ui(method, path, body, headers = {}) {
      const res = await fetch(url + path, {
        method, headers: { ...(body === undefined ? {} : { "content-type": "application/json" }), ...headers },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await res.text();
      return { status: res.status, body: text ? JSON.parse(text) : null };
    },
  };
}

export function fauxModels() {
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  const model = faux.getModel();
  const source: ModelSource = { models, sync: async () => ({ provider: model.provider, modelId: model.id }) };
  return { faux, source };
}

export async function openAgent(api: Api, dbFile: string, source: ModelSource, extra: Extension[] = []) {
  const registry = createRegistry();
  registry.install(defineExtension({
    name: "jobdash",
    sections: sections(() => join(REPO_ROOT, "docs", "agent", "system.md"), () => join(api.dir, "agent", "user.md")),
    tools: makeTools(api.client),
  }));
  for (const e of extra) registry.install(e);
  const harness = await Harness.open(await openNodeSqliteStorage(dbFile), { models: source.models, registry }, ctx);
  const app = createAgentApp({ harness, client: api.client, live: source, ctx, heartbeatMs: 50 });
  return { harness, app };
}
