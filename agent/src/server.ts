// The `agent` process: Pi Durable on SQLite under <data>/agent/, behind Hono.
//   AGENT_PORT  default 8000 (the address the user sees); API_URL default http://127.0.0.1:8001
//   AGENT_SERVE_UI=0 in development, where Vite serves the dashboard.
// Only this process opens <data>/agent/sessions.db (Pi Durable has no cross-process locking).
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createRegistry, defineExtension, Harness } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { serve } from "@hono/node-server";
import { apiClient } from "./api.ts";
import { createAgentApp } from "./app.ts";
import { agentDir, REPO_ROOT, setting } from "./env.ts";
import { LiveModels } from "./model.ts";
import { BASE_PROMPT, clearPromptCache, sections, USER_PROMPT } from "./prompt.ts";
import { templates } from "./commands.ts";
import { pinnedModels } from "./sessions.ts";
import { makeConsult, type Team } from "./team.ts";
import { makeTools } from "./tools.ts";

const ctx = BACKGROUND_CONTEXT;
const port = Number(setting("AGENT_PORT") ?? 8000);
const client = apiClient(setting("API_URL") ?? "http://127.0.0.1:8001");

mkdirSync(agentDir(), { recursive: true });
const registry = createRegistry();
const team: Team = {};                            // the council needs the harness, which needs the tools: filled in below
const install = () => registry.install(defineExtension({ name: "jobdash", sections: sections(), tools: makeTools(client, team) }));
install();
const live = new LiveModels();
for (let attempt = 0; ; attempt++) {             // process-compose starts us once the api is healthy; this is a guard
  try {
    await live.sync(client);
    break;
  } catch (e) {
    if (attempt >= 30) throw e;
    await new Promise((r) => setTimeout(r, 1000));
  }
}
const harness = await Harness.open(await openNodeSqliteStorage(join(agentDir(), "sessions.db")), {
  models: live.models,
  registry,
  settings: {
    compaction: { enabled: true },
    // A hosted endpoint can stall for a minute (a cold start, a gateway hiccup: a forked branch's first request timed
    // out four times in 54s on the default 2s/4s/8s). Wait longer between attempts, and give one attempt the same
    // budget the rest of the app gives a model call (LLM_TIMEOUT, 180s by default).
    retry: { maxRetries: 4, baseDelayMs: 5000, maxAgentDelayMs: 60000 },
    stream: { timeoutMs: (Number(setting("LLM_TIMEOUT")) || 180) * 1000 },
  },
}, ctx);
team.consult = makeConsult(harness, client, live, ctx);
harness.resume();                                 // finish any run a crash or restart interrupted
await live.offer(client, ...await pinnedModels(harness, ctx));

/** /reload: the prompt files are re-read on change anyway; this re-installs the extension (same name: replaced in
 * place, running work keeps its code) so tool and section changes apply from the next request. */
async function reload(): Promise<string[]> {
  clearPromptCache();
  install();
  const loaded = [BASE_PROMPT(), USER_PROMPT()].filter((f) => existsSync(f)).map((f) => f.replace(`${REPO_ROOT}/`, ""));
  return [...loaded, `${makeTools(client).length} tools`, `${templates().length} prompt templates`];
}

const app = createAgentApp({
  harness, client, live, ctx, reload,
  staticDir: setting("AGENT_SERVE_UI") === "0" ? undefined : join(REPO_ROOT, "frontend", "dist"),
});
const server = serve({ fetch: app.fetch, port, hostname: "127.0.0.1" });
console.log(`[agent] up on http://localhost:${port} (api ${client.baseUrl})`);

const shutdown = async () => {
  server.close();
  await harness.close(ctx);
  process.exit(0);
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
