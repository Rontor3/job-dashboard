// Agent-driven apply runs (spec 2026-10-11): skills, the applier profile, and a background run started by the queue.
// Scripted faux model against a real FastAPI on a temp data root, as in team.test.ts.
import { join } from "node:path";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { conversationOf } from "../src/sessions.ts";
import { skills } from "../src/skills.ts";
import { profiles } from "../src/team.ts";
import { ctx, fauxModels, hasPython, openAgent, startApi, type Api } from "./fixtures.ts";

const toolUse = (name: string, args: Parameters<typeof fauxToolCall>[1]) =>
  fauxAssistantMessage([fauxToolCall(name, args)], { stopReason: "toolUse" });
const say = (text: string) => fauxAssistantMessage([fauxText(text)]);

describe("skills and the applier", () => {
  it("ships the apply skill and one per board; the applier runs only the apply tools and reads", () => {
    const names = skills().map((s) => s.name);
    expect(names).toEqual(expect.arrayContaining(["apply", "linkedin", "wellfound", "himalayas", "shortlist"]));
    expect(skills().find((s) => s.name === "apply")!.body).toContain("Walls you never cross");
    const applier = profiles().find((p) => p.name === "applier")!;
    expect(applier.tools).toEqual(expect.arrayContaining(["load_skill", "apply_start", "apply_fill", "apply_submit", "apply_pause"]));
    expect(applier.tools).not.toContain("propose_action");
    expect(applier.tools).not.toContain("update_agent_settings");
  });
});

describe.skipIf(!hasPython)("a background apply run", () => {
  let api: Api;
  beforeAll(async () => { api = await startApi(); }, 30_000);
  afterAll(() => api?.stop());

  it("POST /agent/runs starts an applier session that loads the skill; an unqueued job can't be started", async () => {
    const { faux, source } = fauxModels();
    const { harness, app } = await openAgent(api, join(api.dir, "runs.db"), source);
    faux.setResponses([
      toolUse("load_skill", { name: "apply" }),
      toolUse("apply_start", { job_id: 1 }),
      say("Couldn't start ML Engineer at Acme: it isn't queued."),
    ]);
    const res = await app.request("/agent/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ job_id: 1 }) });
    const { session } = await res.json() as { session: string };
    const conv = (await conversationOf(harness, session, ctx))!;
    let messages: any[] = [];
    for (let i = 0; i < 100; i++) {
      messages = (await conv.context(ctx)).messages as any[];
      if (messages.at(-1)?.role === "assistant" && messages.at(-1).stopReason !== "toolUse") break;
      await new Promise((r) => setTimeout(r, 50));
    }
    expect((await conv.agent(ctx)).instructions).toContain("You are the Applier");
    const results = messages.filter((m) => m.role === "toolResult");
    expect(results[0].content[0].text).toContain("Apply to one job");
    expect(results[1].isError).toBe(true);
    expect(results[1].content[0].text).toContain("not in the apply queue");
    const list = await (await app.request("/agent/sessions")).json() as any;
    expect(list.items.find((s: any) => s.id === session)).toMatchObject({ profile: "applier" });
    expect(list.active).not.toBe(session);                     // a background run doesn't take the user's focus
    expect((await app.request("/agent/runs", { method: "POST", body: "{}" })).status).toBe(422);
    await harness.close(ctx);
  });
});
