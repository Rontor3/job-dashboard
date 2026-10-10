// The tools of the agent-first overhaul: what the agent knows about the user (about-me.md, read by every session),
// the Inbox (notifications it reads and adds to), and the council (asking other agent profiles for their view).
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ToolExecutionResult } from "@earendil-works/pi-durable";
import type { ApiClient } from "./api.ts";
import { keyOf } from "./sessions.ts";
import type { Team } from "./team.ts";
import { asResult, caller, q } from "./tools.ts";

const SECTIONS = ["Target", "Preferences", "Constraints", "Background", "Working style", "Other"] as const;

const text = (body: unknown, isError = false): ToolExecutionResult => ({
  content: [{ type: "text", text: JSON.stringify(body) }],
  isError,
});

export function teamTools(client: ApiClient, team: Team) {
  return [
    // ── What the agent knows about the user ───────────────────────────────────────────────────────────────
    defineTool({
      name: "get_about_me",
      description: "Read what you've learned about the user across sessions (data/agent/about-me.md): their target job, "
        + "preferences, constraints, background and working style, as {section: [facts]}. It's also in your prompt.",
      parameters: Type.Object({}),
      replay: "safe",
      execute: async (_a, api, ctx) => asResult(await caller(client, api, ctx)("GET", "/api/about-me"), (d) => d.sections),
    }),
    defineTool({
      name: "remember",
      description: "Save one durable fact about the user to about-me.md, which every future session reads. Use it the moment "
        + "the user reveals a goal, preference, constraint or fact that no profile field or saved answer holds "
        + "(\"aiming for staff ML infra roles\", \"no gambling or crypto companies\", \"prefers short essays\"). One fact per "
        + "call, in the user's own terms. To correct a fact, pass its exact old wording as `replaces`.",
      parameters: Type.Object({
        section: Type.Union(SECTIONS.map((s) => Type.Literal(s))),
        fact: Type.String({ description: "One short sentence" }),
        replaces: Type.Optional(Type.String({ description: "The exact wording of the fact this replaces" })),
      }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", "/api/about-me/facts", a),
        (d) => ({ saved: d.changed, section: a.section })),
    }),

    // ── The Inbox ──────────────────────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "list_notifications",
      description: "The Inbox's updates, newest first: applications sent, runs that stopped and why, strong new matches "
        + "from Refresh, tracker moves from email, and your own notes. Each has an id, kind, level, title, job_id, data.",
      parameters: Type.Object({ unread_only: Type.Optional(Type.Boolean()) }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("GET", `/api/notifications${q({ limit: 40 })}`),
        (d) => ({ unread: d.unread, items: (a.unread_only ? d.items.filter((i: { read_at: unknown }) => !i.read_at) : d.items)
          .map(({ id, at, kind, level, title, body, job_id, data }: Record<string, unknown>) => ({ id, at, kind, level, title, body, job_id, data })) })),
    }),
    defineTool({
      name: "notify_user",
      description: "Put a card in the user's Inbox: for work you finished in the background, or something that needs them "
        + "later (\"Shortlist of 8 ready\", \"3 answers to check\"). level: info | success | action | warning. Attach "
        + "job_ids when the card is about jobs, so they can act on them from the card. Don't use it to reply in chat.",
      parameters: Type.Object({
        title: Type.String(),
        body: Type.Optional(Type.String()),
        level: Type.Optional(Type.Union(["info", "success", "action", "warning"].map((l) => Type.Literal(l)))),
        job_ids: Type.Optional(Type.Array(Type.Integer())),
      }),
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", "/api/notifications", { level: "info", ...a })),
    }),
    defineTool({
      name: "dismiss_notification",
      description: "Clear one Inbox card by id once it's dealt with.",
      parameters: Type.Object({ id: Type.Integer() }),
      replay: "safe",
      execute: async (a, api, ctx) => asResult(await caller(client, api, ctx)("POST", `/api/notifications/${a.id}/dismiss`)),
    }),

    // ── The council ────────────────────────────────────────────────────────────────────────────────────────
    defineTool({
      name: "consult_agents",
      description: "Ask other agents for their view, in parallel, and get their answers back. Profiles: critic (a skeptical "
        + "hiring manager who finds what will get this rejected), advocate (the strongest honest case for the user), scout "
        + "(finds and shortlists jobs), or the user's own. Use critic + advocate for an adversarial review of a shortlist, an "
        + "answer, an essay or the résumé, then weigh both and tell the user what you'd change. The brief must stand alone: "
        + "they don't see this conversation, so include the job ids, the text to review and what you want back.",
      parameters: Type.Object({
        brief: Type.String({ description: "Everything they need: the material, the job ids, the question" }),
        profiles: Type.Optional(Type.Array(Type.String(), { description: "Default [\"critic\", \"advocate\"]" })),
      }),
      execute: async (a, api, ctx) => {
        if (!team.consult) return text({ error: "the council isn't available in this process" }, true);
        const names = [...new Set(a.profiles?.length ? a.profiles : ["critic", "advocate"])].slice(0, 4);
        const opinions = await team.consult(await keyOf(api, api.conversationId, ctx), a.brief, names);
        return text({ opinions: opinions.map(({ profile, answer, ok }) => ({ profile, ok, answer })) }, opinions.every((o) => !o.ok));
      },
    }),
  ];
}
