// The v1 tools (spec: profile and identity, the question bank and Needs-you, preferences and settings, jobs,
// setup state). Each is one or two HTTP calls to FastAPI with the session and tool-call ids as headers, so every
// change lands in the change log with Undo. A tool is `replay: "safe"` only when it sets a value: rerunning it
// after a crash lands on the same state and logs nothing new. There is deliberately no tool that submits an
// application, reads a secret value, or touches files outside the data FastAPI exposes.
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ToolExecutionApi, type ToolExecutionResult } from "@earendil-works/pi-durable";
import { SECRET_KEYS, WIDGET_TOOLS, type ChangeSummary } from "@jobdash/agent-protocol";
import type { Context } from "@earendil-works/chord";
import type { ApiClient, ApiResult } from "./api.ts";
import { keyOf } from "./sessions.ts";

const MAX_RESULT = 12_000;

const clip = (text: string) => (text.length > MAX_RESULT ? text.slice(0, MAX_RESULT) + "\n…[cut]" : text);

function asResult(r: ApiResult, shape?: (data: any) => unknown): ToolExecutionResult {
  const detail = (r.data as { detail?: unknown } | null)?.detail ?? r.data;
  const payload = r.ok ? (shape ? shape(r.data) : r.data) : { error: r.status, detail };
  const changes: ChangeSummary[] = r.changes;
  const body = changes.length
    ? { result: payload, changed: changes.map((c) => ({ change_id: c.id, what: `${c.entity} ${c.entity_id} ${c.field}`, before: c.before, after: c.after })) }
    : payload;
  return {
    content: [{ type: "text", text: clip(JSON.stringify(body)) }],
    isError: !r.ok,
    details: { changes } as unknown as never,
  };
}

const widget = (text: string, details: Record<string, unknown>): ToolExecutionResult => ({
  content: [{ type: "text", text }],
  details: details as never,
  control: { terminate: true },
});

type Caller = (method: string, path: string, body?: unknown) => Promise<ApiResult>;

type CallApi = Pick<ToolExecutionApi, "conversationId" | "callId" | "snapshot">;

/** Bind the client to the calling session (its UUID key) and tool call. */
const caller = (client: ApiClient, api: CallApi, ctx: Context): Caller =>
  async (method, path, body) => client.call(method, path, { body, session: await keyOf(api, api.conversationId, ctx), message: api.callId });

const q = (params: Record<string, unknown>) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
  return s.size ? `?${s}` : "";
};

const JOB_FIELDS = ["id", "title", "company", "location", "status", "verdict", "llm_score", "embed_score", "source", "job_url", "apply_type"];
const pick = (o: Record<string, unknown>, keys: string[]) => Object.fromEntries(keys.filter((k) => k in o).map((k) => [k, o[k]]));

export function makeTools(client: ApiClient) {
  return [
    // ── Profile and identity ──────────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "get_profile",
      description: "Read the application profile: name, contact, location, work authorization, notice period, salary, demographics.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/application-profile")),
    }),
    defineTool({
      name: "update_profile",
      description: "Set application-profile fields. Pass only the fields to change, e.g. {\"phone\": \"+91 98…\"}. "
        + "Fields: full_name, email, phone, location, postal_code, linkedin_url, github_url, portfolio_url, work_authorization, "
        + "years_experience, willing_to_relocate (true/false), notice_period, salary_expectation, current_ctc, reason_for_change, "
        + "gender, ethnicity, veteran_status, disability_status.",
      parameters: Type.Object({ fields: Type.Record(Type.String(), Type.Union([Type.String(), Type.Boolean(), Type.Null()])) }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/application-profile", a.fields)),
    }),
    defineTool({
      name: "get_candidate_profile",
      description: "Read the candidate profile (markdown: experience, skills, goals) that ranking and drafting use.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/candidate-profile")),
    }),
    defineTool({
      name: "write_candidate_profile",
      description: "Replace the whole candidate profile markdown. Read it first and keep what the user didn't ask to change. "
        + "Never invent facts: only what the user or their résumé says.",
      parameters: Type.Object({ text: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/candidate-profile", { text: a.text }), () => ({ saved: true })),
    }),
    defineTool({
      name: "read_resume",
      description: "Read the text of the résumé the user uploaded (the one sent to employers).",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/current-resume/text")),
    }),
    defineTool({
      name: WIDGET_TOOLS.upload,
      description: "Show the user an upload box for their résumé PDF. Ends your turn; you'll hear when it's uploaded.",
      parameters: Type.Object({ reason: Type.String({ description: "One line on why you need it" }) }),
      replay: "safe",
      execute: async (a) => widget("Asked the user to upload their résumé. Wait for them.", { widget: "upload", reason: a.reason }),
    }),

    // ── Question bank and Needs-you ───────────────────────────────────────────────────────────────────────
    defineTool({
      name: "search_answers",
      description: "Search the question bank (canonical questions answered once, reused on every form). Empty query lists all.",
      parameters: Type.Object({ query: Type.Optional(Type.String()) }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/answers${q({ q: a.query })}`), (d) => ({
        unanswered: d.unanswered,
        answers: d.answers.slice(0, 40).map((e: any) => pick(e, ["id", "question", "atype", "value", "rule", "rule_help", "needs_input", "asked_in"])),
      })),
    }),
    defineTool({
      name: "set_answer",
      description: "Set the saved answer of an existing question-bank entry (by its id from search_answers).",
      parameters: Type.Object({ entry_id: Type.String(), answer: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/answers", { entry_id: a.entry_id, answer: a.answer })),
    }),
    defineTool({
      name: "add_answer",
      description: "Add a new question-bank entry with its answer, for a question no entry covers yet.",
      parameters: Type.Object({ question: Type.String(), answer: Type.String() }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/answers", { question: a.question, answer: a.answer })),
    }),
    defineTool({
      name: "list_needs_you",
      description: "What the apply agent is waiting on: questions blocking applications, guesses to confirm, unanswered bank entries.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/inbox")),
    }),
    defineTool({
      name: "answer_blocking_question",
      description: "Answer a question that is holding up an application (job_id and row_id from list_needs_you). "
        + "remember=true also saves it to the bank for every future form; false answers this application only.",
      parameters: Type.Object({ job_id: Type.Integer(), row_id: Type.Integer(), answer: Type.String(), remember: Type.Boolean() }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", `/api/jobs/${a.job_id}/questions/${a.row_id}/reply`,
        { answer: a.answer, save_as: a.remember ? "new" : "once" })),
    }),
    defineTool({
      name: "review_guess",
      description: "Confirm or correct an answer the apply agent guessed (row_id from list_needs_you guesses). "
        + "Give `answer` to correct it; omit it to confirm the guess is right.",
      parameters: Type.Object({ row_id: Type.Integer(), answer: Type.Optional(Type.String()) }),
      execute: async (a, api, ctx) => {
        const call = caller(client, api, ctx);
        if (!a.answer) return asResult(await call("POST", `/api/application-qa/${a.row_id}/review`, { verdict: "correct" }));
        const path = `/api/application-qa/${a.row_id}/answer`;
        const fixed = await call("PUT", path, { answer: a.answer, save_as: "entry" });     // the saved answer it came from
        return asResult(fixed.status === 422 ? await call("PUT", path, { answer: a.answer, save_as: "new" }) : fixed);
      },
    }),

    // ── Preferences and agent settings ────────────────────────────────────────────────────────────────────
    defineTool({
      name: "get_settings",
      description: "Read the apply agent's settings: confidence thresholds, which job sites to browse, queue settings, "
        + "auto-submit switches, the app config (LLM endpoint and model), and the job preferences learned from clicks.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => {
        const call = caller(client, api, ctx);
        const parts = await Promise.all(["/api/agent-settings", "/api/queue/settings", "/api/queue/autosubmit", "/api/config", "/api/preferences"]
          .map((p) => call("GET", p)));
        const [agent, queue, autosubmit, config, preferences] = parts.map((r) => r.data);
        return { content: [{ type: "text", text: clip(JSON.stringify({ agent, queue, autosubmit, config, preferences })) }] };
      },
    }),
    defineTool({
      name: "update_agent_settings",
      description: "Change agent settings: answer_confidence_min and qbank_confident_min (0-100), browser_<site>_enabled "
        + "(true/false; sites: linkedin, naukri, wellfound, instahyre, iimjobs, indeed, ycstartups).",
      parameters: Type.Object({ settings: Type.Record(Type.String(), Type.Union([Type.Integer(), Type.Boolean()])) }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/agent-settings", a.settings)),
    }),
    defineTool({
      name: "set_config",
      description: "Change an app setting: LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT, LLM_REASONING_EFFORT, LLM_NO_TEMPERATURE, "
        + "LLM_CONTEXT_WINDOW, AGENT_CDP_PORT, AGENT_CHROME_PATH. Empty value = back to the default. The result says if a "
        + "restart is needed; tell the user, never restart anything yourself. Not for API keys: use request_secret.",
      parameters: Type.Object({ key: Type.String(), value: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", `/api/config/${encodeURIComponent(a.key)}`, { value: a.value })),
    }),

    // ── Jobs ──────────────────────────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "search_jobs",
      description: "Search scraped jobs. status: saved|applied|interviewing|offer|rejected|dismissed; sort: embed|learned|date.",
      parameters: Type.Object({
        query: Type.Optional(Type.String()), status: Type.Optional(Type.String()),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
      }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(
        await caller(client, api, ctx)("GET", `/api/jobs${q({ q: a.query, status: a.status, limit: a.limit ?? 15 })}`),
        (d) => ({ total: d.total, jobs: d.jobs.map((j: any) => pick(j, JOB_FIELDS)) })),
    }),
    defineTool({
      name: "get_job",
      description: "One job's details: description, fit (strengths, gaps), status, apply details.",
      parameters: Type.Object({ job_id: Type.Integer() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/jobs/${a.job_id}`), (d) => ({
        ...pick(d, [...JOB_FIELDS, "strengths", "gaps", "flags", "apply_details", "industry", "company_type"]),
        description: String(d.description ?? "").slice(0, 3000),
      })),
    }),
    defineTool({
      name: "set_job_status",
      description: "Set a job's tracker status: saved, applied, interviewing, offer, rejected, dismissed.",
      parameters: Type.Object({ job_id: Type.Integer(), status: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PATCH", `/api/jobs/${a.job_id}/status`, { status: a.status })),
    }),
    defineTool({
      name: "set_apply_details",
      description: "Per-application facts for one job's company questions; anything unset answers No: referrer (name), "
        + "relatives, applied_before, interviewed_before, worked_before (true/false). Sends all five, so read get_job first.",
      parameters: Type.Object({
        job_id: Type.Integer(), referrer: Type.Optional(Type.String()), relatives: Type.Optional(Type.Boolean()),
        applied_before: Type.Optional(Type.Boolean()), interviewed_before: Type.Optional(Type.Boolean()),
        worked_before: Type.Optional(Type.Boolean()),
      }),
      replay: "safe",
      execute: async ({ job_id, ...details }, api, ctx) => asResult(await caller(client, api, ctx)("PUT", `/api/jobs/${job_id}/apply-details`, details)),
    }),

    // ── What the app is doing ────────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "get_overview",
      description: "Where things stand: job counts by status, the apply queue (items, running, whether the worker is up), "
        + "Refresh and hiring-refresh status, and which logged-in job sites are switched on.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => {
        const call = caller(client, api, ctx);
        const [stats, queue, refresh, hiring, settings] = await Promise.all([
          call("GET", "/api/stats"), call("GET", "/api/queue"), call("GET", "/api/refresh/status"),
          call("GET", "/api/hiring/refresh/status"), call("GET", "/api/agent-settings"),
        ]);
        const sites = Object.entries((settings.data ?? {}) as Record<string, unknown>)
          .filter(([k]) => /^browser_.*_enabled$/.test(k)).map(([k, v]) => [k.replace(/^browser_|_enabled$/g, ""), v]);
        const st = (stats.data ?? {}) as Record<string, unknown>;
        return asResult({ ...stats, data: {
          jobs: pick(st, ["total", "new", "saved", "applied", "interviewing", "offer", "rejected", "failed", "dismissed", "unranked"]),
          queue: queue.data, refresh: refresh.data, hiring_refresh: hiring.data, browser_sites: Object.fromEntries(sites),
        } });
      },
    }),
    defineTool({
      name: "get_tracker",
      description: "The Applied board: jobs by column (saved, applied, failed, interviewing, offer, archived), with queue state "
        + "and why an application failed or was parked.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/tracker"), (d) => Object.fromEntries(
        Object.entries(d as Record<string, any[]>).map(([col, jobs]) => [col, jobs.map((j) => pick(j, [
          "id", "title", "company", "status", "source", "queue_state", "queue_reason", "error_detail", "interview_round"]))]))),
    }),
    defineTool({
      name: "get_apply_run",
      description: "The apply agent's latest run on one job: each step (page reached, what stopped it, what it waited on a "
        + "human for) and the questions it saw. Use it to explain why an application failed or is parked.",
      parameters: Type.Object({ job_id: Type.Integer() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/jobs/${a.job_id}/agent-runs/latest`),
        (d) => ({ ...d, steps: (d.steps ?? []).map(({ screenshot: _s, ...step }: Record<string, unknown>) => step) })),
    }),
    defineTool({
      name: "list_hiring_posts",
      description: "LinkedIn hiring posts the hiring refresh kept (role, company, fit, contact status), newest first.",
      parameters: Type.Object({ within_hours: Type.Optional(Type.Integer({ minimum: 1, maximum: 720 })) }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/hiring/posts${q({ within_hours: a.within_hours ?? 168 })}`),
        (d) => ({ posts: (d.posts ?? []).slice(0, 30).map((p: Record<string, unknown>) => ({ ...p, text: String(p.text ?? "").slice(0, 400) })) })),
    }),

    // ── Setup state and secrets ───────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "get_setup_state",
      description: "Onboarding progress (data/setup-state.md) and which keys are set in .env (yes/no only, never values).",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => {
        const call = caller(client, api, ctx);
        const [state, secrets] = await Promise.all([call("GET", "/api/setup-state"), call("GET", "/api/secrets")]);
        return { content: [{ type: "text", text: clip(JSON.stringify({ setup_state: state.data, secrets_present: (secrets.data as any)?.secrets })) }] };
      },
    }),
    defineTool({
      name: "update_setup_state",
      description: "Replace data/setup-state.md (status: partial|complete, init_version, which groups are done).",
      parameters: Type.Object({ text: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", "/api/setup-state", { text: a.text }), () => ({ saved: true })),
    }),
    defineTool({
      name: WIDGET_TOOLS.secret,
      description: `Show the user a password field for one key (${SECRET_KEYS.join(", ")}). The value goes straight from `
        + "their browser to .env; you never see it, only that it's set. Ends your turn.",
      parameters: Type.Object({ key: Type.Union(SECRET_KEYS.map((k) => Type.Literal(k))), reason: Type.String() }),
      replay: "safe",
      execute: async (a) => widget(`Asked the user to enter ${a.key}. Wait for them.`, { widget: "secret", key: a.key, reason: a.reason }),
    }),

    // ── Consequential actions, Undo, history ──────────────────────────────────────────────────────────────
    defineTool({
      name: WIDGET_TOOLS.confirm,
      description: "Ask the user to confirm a consequential action: queueing or applying to a job, starting the queue, Refresh, "
        + "a mail scan, auto-submit switches, queue settings, or any delete. Give the exact API request and a one-line summary. "
        + "A Confirm / Cancel box appears; the action runs only if THEY press Confirm. You can't confirm. Ends your turn.",
      parameters: Type.Object({
        method: Type.Union([Type.Literal("POST"), Type.Literal("PUT"), Type.Literal("PATCH"), Type.Literal("DELETE")]),
        path: Type.String({ description: "e.g. /api/queue/autosubmit or /api/answers?entry_id=x" }),
        body: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
        summary: Type.String(),
      }),
      execute: async (a, api, ctx) => {
        const r = await caller(client, api, ctx)("POST", "/api/confirmations", { method: a.method, path: a.path, body: a.body ?? null, summary: a.summary });
        if (!r.ok) return asResult(r);
        return widget(`Waiting for the user to confirm: ${a.summary}`, { widget: "confirm", confirmation: r.data });
      },
    }),
    defineTool({
      name: "undo_change",
      description: "Undo one change by its change_id (from a tool result or recent_changes).",
      parameters: Type.Object({ change_id: Type.Integer() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", `/api/changes/${a.change_id}/undo`)),
    }),
    defineTool({
      name: "recent_changes",
      description: "The changes made in this session, newest first, with ids for undo_change.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/changes${q({ session_id: await keyOf(api, api.conversationId, ctx), limit: 30 })}`)),
    }),
  ];
}

export const TOOL_NAMES = makeTools(null as unknown as ApiClient).map((t) => t.name);
