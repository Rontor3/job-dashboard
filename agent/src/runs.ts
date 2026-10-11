// Apply runs in the background (spec 2026-10-11-agent-driven-apply-design.md): the apply queue asks for one job at a
// time (`POST /agent/runs {job_id}`); each gets its own session on the `applier` profile, like the council's child
// sessions, so the user can open it and read every step. The route answers at once; the run's verdict lands in
// FastAPI's apply_run row, which the queue watches.
import { randomUUID } from "node:crypto";
import type { Context } from "@earendil-works/chord";
import type { Harness } from "@earendil-works/pi-durable";
import type { ApiClient } from "./api.ts";
import type { ModelSource } from "./model.ts";
import { conversationOf, createSession } from "./sessions.ts";
import { applyProfile, findProfile } from "./team.ts";

export const APPLY_PROFILE = "applier";

export function brief(jobId: number): string {
  return `Apply to job ${jobId}. Load the \`apply\` skill first and follow it to the end: start, reach the form, `
    + `fill every page from the user's own data, then submit, pause or skip. Finish with one line saying where it stands.`;
}

export async function startApplyRun(harness: Harness, client: ApiClient, live: ModelSource, ctx: Context, jobId: number): Promise<string> {
  const model = await live.sync(client);
  const key = await createSession(harness, model, ctx, { activate: false, profile: APPLY_PROFILE, title: `Apply: job ${jobId}` });
  const conv = (await conversationOf(harness, key, ctx))!;
  await applyProfile(conv, findProfile(APPLY_PROFILE), ctx);
  await conv.submit({ type: "input", content: brief(jobId), requestId: randomUUID() }, ctx);
  return key;
}
