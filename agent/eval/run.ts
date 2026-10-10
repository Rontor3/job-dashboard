// The opt-in live eval (`mise run eval:agent`): about ten scenarios against the real model the config table names,
// on a temp data root (tests/agent_api_app.py with AGENT_EVAL_SEED=1) and a temp session store. Each scenario asks
// in a fresh session, then checks what changed through the api, not the wording of the reply. It never touches the
// user's data; it does call the configured model, so it is not part of `mise run test`.
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { encodeElementMessage } from "@jobdash/agent-protocol";
import { REPO_ROOT } from "../src/env.ts";
import { LiveModels } from "../src/model.ts";
import { conversationOf } from "../src/sessions.ts";
import { ctx, openAgent, PYTHON, startApi, type Api } from "../test/fixtures.ts";

const LLM_KEYS = ["LLM_BASE_URL", "LLM_MODEL", "LLM_TIMEOUT", "LLM_REASONING_EFFORT", "LLM_NO_TEMPERATURE", "LLM_CONTEXT_WINDOW"];

/** The real model settings (config table, else .env), read from the user's data root without changing it. */
function liveSettings(): Record<string, string> {
  const code = "import json; from job_dashboard import config; from job_dashboard.env import load_app_env; "
    + "load_app_env(); print(json.dumps(config.snapshot()))";
  const r = spawnSync(PYTHON, ["-c", code], { cwd: REPO_ROOT, env: { ...process.env, PYTHONPATH: "src" }, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`couldn't read the model config: ${r.stderr}`);
  const all = JSON.parse(r.stdout) as Record<string, string | null>;
  return Object.fromEntries(LLM_KEYS.filter((k) => all[k]).map((k) => [k, String(all[k])]));
}

type Agent = Awaited<ReturnType<typeof session>>;

async function session(api: Api, live: LiveModels, name: string) {
  const { harness, app } = await openAgent(api, join(api.dir, `${name}.db`), live);
  const post = async (path: string, body?: unknown) => {
    const res = await app.request(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
    return res.json() as Promise<any>;
  };
  const id = (await post("/agent/sessions")).id as string;
  let n = 0;
  const ask = async (content: string) => {
    const { submission } = await post(`/agent/sessions/${id}/messages`, { content, requestId: `${name}-${++n}` });
    return (await harness.submission(submission, ctx))!.wait(ctx);
  };
  const entries = async () => {
    const view = await (await conversationOf(harness, id, ctx))!.viewState(ctx);
    const out = view.value.entries as any[];
    view.dispose();
    return out;
  };
  const toolsCalled = async () => (await entries()).flatMap((e) => (e.kind === "pi.assistant" ? e.model[0].content : []))
    .filter((b: any) => b.type === "toolCall").map((b: any) => b.name as string);
  const reply = async () => (await entries()).filter((e) => e.kind === "pi.assistant").at(-1)?.model[0].content
    .filter((b: any) => b.type === "text").map((b: any) => b.text).join("") ?? "";
  return { id, ask, toolsCalled, reply, close: () => harness.close(ctx) };
}

interface Scenario {
  name: string;
  /** Messages sent in order, each waiting for the run to finish. */
  say: string[];
  check(api: Api, a: Agent): Promise<string | true>;
}

const get = async (api: Api, path: string) => (await api.ui("GET", path)).body;
const expectThat = (ok: boolean, why: string) => (ok ? true : why);

const SCENARIOS: Scenario[] = [
  {
    name: "says what the apply agent is waiting on",
    say: ["What is the apply agent waiting on? Just tell me, don't change anything."],
    check: async (_api, a) => {
      const tools = await a.toolsCalled();
      return expectThat(tools.includes("list_needs_you") && /notice/i.test(await a.reply()), `tools ${tools}; reply: ${(await a.reply()).slice(0, 120)}`);
    },
  },
  {
    name: "answers the blocking question",
    say: ["My notice period is 30 days. Answer the question that's blocking my Acme application."],
    check: async (api) => {
      const open = (await get(api, "/api/inbox")).questions.filter((q: any) => /notice/i.test(q.label));
      return expectThat(open.length === 0, `still open: ${JSON.stringify(open)}`);
    },
  },
  {
    name: "fixes a profile field",
    say: ["Set my phone number to +91 98765 43210."],
    check: async (api) => {
      const phone = String((await get(api, "/api/application-profile")).phone ?? "");
      return expectThat(phone.replace(/\D/g, "").endsWith("9876543210"), `phone is ${phone}`);
    },
  },
  {
    name: "undoes its own change",
    say: ["Set my location to Atlantis.", "Actually, undo that."],
    check: async (api) => {
      const loc = (await get(api, "/api/application-profile")).location;
      return expectThat(!/atlantis/i.test(String(loc ?? "")), `location is ${loc}`);
    },
  },
  {
    name: "sets per-application apply details",
    say: ["For the Acme ML Engineer job, I was referred by Priya Sharma."],
    check: async (api) => {
      const d = (await get(api, "/api/jobs/1")).apply_details ?? {};
      return expectThat(/priya/i.test(JSON.stringify(d)), `apply details ${JSON.stringify(d)}`);
    },
  },
  {
    name: "moves a job on the tracker",
    say: ["I applied to the Acme ML Engineer job myself; mark it applied."],
    check: async (api) => {
      const s = (await get(api, "/api/jobs/1")).status;
      return expectThat(s === "applied", `status is ${s}`);
    },
  },
  {
    name: "changes a threshold",
    say: ["Lower the answer confidence threshold to 50."],
    check: async (api) => {
      const v = (await get(api, "/api/agent-settings")).answer_confidence_min;
      return expectThat(v === 50, `answer_confidence_min is ${v}`);
    },
  },
  {
    name: "asks before turning on auto-submit",
    say: ["Turn on auto-submit for LinkedIn."],
    check: async (api, a) => {
      const on = (await get(api, "/api/queue/autosubmit")).linkedin;
      const tools = await a.toolsCalled();
      return expectThat(!on && tools.includes("propose_action"), `linkedin=${on}; tools ${tools}`);
    },
  },
  {
    name: "takes a key through the secret box, not the chat",
    say: ["I want to set up my Tinyfish API key for company research."],
    check: async (api, a) => {
      const tools = await a.toolsCalled();
      const env = (await get(api, "/api/secrets")).secrets;
      return expectThat(tools.includes("request_secret") && !env.TINYFISH_API_KEY, `tools ${tools}`);
    },
  },
  {
    name: "explains an element from the popover",
    say: [encodeElementMessage({ anchor: "job:1", tab: "jobs", text: "ML Engineer · Acme" }, "What is this job about?")],
    check: async (_api, a) => {
      const tools = await a.toolsCalled();
      return expectThat(tools.includes("get_job") && (await a.reply()).length > 20, `tools ${tools}`);
    },
  },
];

const only = process.argv[2];
const api = await startApi({ ...liveSettings(), AGENT_EVAL_SEED: "1" });
const live = new LiveModels();
const model = await live.sync(api.client);
console.log(`live eval on ${model.modelId}\n`);
let passed = 0;
const chosen = SCENARIOS.filter((s) => !only || s.name.includes(only));
try {
  for (const [i, s] of chosen.entries()) {
    const started = Date.now();
    const a = await session(api, live, `eval-${i}`);
    let verdict: string | true;
    try {
      for (const m of s.say) {
        const r = await a.ask(m);
        if (r.status !== "done") throw new Error(`run ${r.status}`);
      }
      verdict = await s.check(api, a);
    } catch (e) {
      verdict = `error: ${(e as Error).message}`;
    } finally {
      await a.close();
    }
    if (verdict === true) passed++;
    console.log(`${verdict === true ? "PASS" : "FAIL"}  ${s.name} (${((Date.now() - started) / 1000).toFixed(0)}s)`
      + (verdict === true ? "" : `\n      ${verdict}`));
  }
} finally {
  api.stop();
}
console.log(`\n${passed}/${chosen.length} passed`);
process.exit(passed === chosen.length ? 0 : 1);
