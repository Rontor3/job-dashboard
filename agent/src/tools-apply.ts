// The apply tools (spec 2026-10-11-agent-driven-apply-design.md): the agent drives one application through FastAPI's
// /api/apply-sessions routes, which hold the live page in the agent Chrome. The page is read DOM-first (fields with
// ids, values and grounded suggestions); the agent decides values, the server fills and checks them. Submit is
// gated server-side by the user's standing auto-submit authorization and the job's priority: the agent can't reach
// a submit the user hasn't switched on. Captchas are never solved: a captcha ends the run as skipped.
import { Type } from "@earendil-works/pi-ai";
import { defineTool } from "@earendil-works/pi-durable";
import type { ApiClient } from "./api.ts";
import { skills } from "./skills.ts";
import { asResult, caller } from "./tools.ts";

const JOB = Type.Integer({ description: "the job id" });
const path = (id: number, tail = "") => `/api/apply-sessions/${id}${tail}`;

export function applyTools(client: ApiClient) {
  return [
    defineTool({
      name: "load_skill",
      description: "Load a skill's full instructions by name (the list is in your system prompt). Load `apply` before any application run.",
      parameters: Type.Object({ name: Type.String() }),
      replay: "safe",
      execute: async (a) => {
        const s = skills().find((k) => k.name === a.name);
        const text = s ? s.body : `No skill named ${a.name}. Skills: ${skills().map((k) => k.name).join(", ") || "none"}.`;
        return { content: [{ type: "text", text }], isError: !s, details: {} as never };
      },
    }),
    defineTool({
      name: "apply_start",
      description: "Open a queued job's page in the agent Chrome (or carry on in the tab where its run paused). "
        + "Says board/site, the job's priority, and ends the run as skipped at a wall (captcha, closed, sign-in needed).",
      parameters: Type.Object({ job_id: JOB }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id))),
    }),
    defineTool({
      name: "apply_reach",
      description: "From the job page to the application form (clicks Apply, opens a board's apply dialog, follows to the company site).",
      parameters: Type.Object({ job_id: JOB }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/reach"))),
    }),
    defineTool({
      name: "apply_snapshot",
      description: "The current form page: fields {id, label, kind, required, options, value, suggestion:{value, source}}, "
        + "the Next control (`next`) and the Submit control (`submit`). Suggestions come from the user's own data.",
      parameters: Type.Object({ job_id: JOB }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", path(a.job_id, "/form"))),
    }),
    defineTool({
      name: "apply_fill",
      description: "Fill fields on the current page. `accept_suggestions: true` fills every suggestion you don't override. "
        + "Each answer: {id, value, source, citation}. source is where the value came from: profile | resume | qbank | "
        + "ingredients | jd | option | human, with citation saying exactly where (e.g. \"profile.notice_period\", "
        + "\"qbank:salary_expectation\", \"résumé: Experience, Acme 2021-24\"). Anything you composed yourself: "
        + "source \"agent\" (no citation): it is shown to the user as written by you, not their words. "
        + "For a file field use value \"resume\". Returns what was rejected, what didn't stick, required fields still empty, and the page after.",
      parameters: Type.Object({
        job_id: JOB,
        accept_suggestions: Type.Optional(Type.Boolean()),
        answers: Type.Optional(Type.Array(Type.Object({
          id: Type.String(),
          value: Type.Union([Type.String(), Type.Boolean(), Type.Number()]),
          source: Type.String(),
          citation: Type.Optional(Type.String()),
        }))),
      }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/fill"),
        { answers: a.answers ?? [], accept_suggestions: a.accept_suggestions ?? false })),
    }),
    defineTool({
      name: "apply_advance",
      description: "Click Next / Continue on the current page (never the final Submit). Snapshot again after it.",
      parameters: Type.Object({ job_id: JOB }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/advance"))),
    }),
    defineTool({
      name: "apply_submit",
      description: "Submit the application on its last page. Goes through only where the user switched auto-submit on and "
        + "the job's priority allows it; otherwise returns {held, reasons}: then pause with reason \"review\", never retry.",
      parameters: Type.Object({ job_id: JOB }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/submit"))),
    }),
    defineTool({
      name: "apply_pause",
      description: "Pause the run when only the user can go on: the tab stays open, the Inbox shows the status and your "
        + "questions. reason: needs_answers | review | sensitive_field | stuck. questions: [{id, why}] for fields you couldn't answer.",
      parameters: Type.Object({
        job_id: JOB,
        reason: Type.String(),
        detail: Type.String({ description: "one or two plain sentences for the user: where it stands and what's needed" }),
        questions: Type.Optional(Type.Array(Type.Object({ id: Type.String(), why: Type.String() }))),
      }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/pause"),
        { reason: a.reason, detail: a.detail, questions: a.questions ?? [] })),
    }),
    defineTool({
      name: "apply_skip",
      description: "End the run without applying: a wall you must not cross (captcha, account sign-up), the job isn't eligible, or it can't be done.",
      parameters: Type.Object({ job_id: JOB, reason: Type.String(), detail: Type.String() }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/skip"),
        { reason: a.reason, detail: a.detail })),
    }),
    defineTool({
      name: "apply_dialog",
      description: "Press one button of the dialog open over the page (a step result shows it as `dialog`: its kind, text and "
        + "buttons). Use a button's exact text. Submit, sign-in, sign-up and payment buttons are refused. Returns the page after it.",
      parameters: Type.Object({ job_id: JOB, button: Type.String() }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", path(a.job_id, "/dialog"), { button: a.button })),
    }),
    defineTool({
      name: "apply_page_text",
      description: "The current page's visible text, for when the fields alone don't explain what the page wants.",
      parameters: Type.Object({ job_id: JOB }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", path(a.job_id, "/text"))),
    }),
    defineTool({
      name: "set_job_priority",
      description: "Set a job's priority: low | normal | high | dream. At high and dream, an answer you wrote yourself holds submit for the user's review.",
      parameters: Type.Object({ job_id: JOB, level: Type.String() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("PUT", `/api/jobs/${a.job_id}/priority`, { level: a.level })),
    }),
  ];
}
