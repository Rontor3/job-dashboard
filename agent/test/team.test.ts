// The agent-first overhaul's agent side: profiles, the council, what the agent learns about the user, the Inbox.
// Scripted faux model against a real FastAPI on a temp data root, as in e2e.test.ts.
import { join } from "node:path";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { conversationOf } from "../src/sessions.ts";
import { profiles } from "../src/team.ts";
import { ctx, fauxModels, hasPython, openAgent, startApi, type Api } from "./fixtures.ts";

const toolUse = (name: string, args: Parameters<typeof fauxToolCall>[1]) =>
  fauxAssistantMessage([fauxToolCall(name, args)], { stopReason: "toolUse" });
const say = (text: string) => fauxAssistantMessage([fauxText(text)]);

describe("profiles", () => {
  it("ships scout, critic and advocate, each with a prompt and a tool set; a user profile overrides by name", () => {
    const base = profiles();
    expect(base.map((p) => p.name)).toEqual(expect.arrayContaining(["scout", "critic", "advocate"]));
    for (const p of base) expect(p.body.length).toBeGreaterThan(100);
    expect(base.find((p) => p.name === "critic")!.tools).not.toContain("propose_action");
    expect(base.find((p) => p.name === "scout")!.tools).toContain("consult_agents");
  });
});

describe.skipIf(!hasPython)("the team over FastAPI", () => {
  let api: Api;
  beforeAll(async () => { api = await startApi(); }, 30_000);
  afterAll(() => api?.stop());

  async function agent(name: string, profile?: string) {
    const { faux, source } = fauxModels();
    const { harness, app } = await openAgent(api, join(api.dir, `${name}.db`), source);
    const call = async (method: string, path: string, body?: unknown) =>
      (await app.request(path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) })).json() as Promise<any>;
    const session = (await call("POST", "/agent/sessions", profile ? { profile } : {})).id as string;
    let n = 0;
    const ask = async (content: string) => {
      const { submission } = await call("POST", `/agent/sessions/${session}/messages`, { content, requestId: `${name}-${++n}` });
      return (await harness.submission(submission, ctx))!.wait(ctx);
    };
    return { faux, harness, call, session, ask };
  }

  it("a session started as the critic runs with its prompt and only its tools; /profile switches back", async () => {
    const a = await agent("profile", "critic");
    const conv = (await conversationOf(a.harness, a.session, ctx))!;
    let state = await conv.agent(ctx);
    expect(state.instructions).toContain("You are the Critic");
    expect(state.tools.map((t) => t.name)).not.toContain("update_profile");
    expect((await a.call("GET", "/agent/sessions")).items[0].profile).toBe("critic");

    expect((await a.call("POST", `/agent/sessions/${a.session}/command`, { name: "profile", args: "default" })).message).toBe("Profile: default");
    state = await conv.agent(ctx);
    expect(state.instructions).toBeUndefined();
    expect(state.tools.map((t) => t.name)).toContain("update_profile");
    expect((await a.call("POST", "/agent/sessions", { profile: "nobody" })).detail).toBe("no such profile");
    await a.harness.close(ctx);
  });

  it("consult_agents runs a critic in its own child session and hands its answer back", async () => {
    const a = await agent("council");
    a.faux.setResponses([
      toolUse("consult_agents", { brief: "Review jobs 1 and 2 against a staff ML infra target.", profiles: ["critic"] }),
      say("Strike job 2: it's a junior role. Verdict: keep 1, strike 1"),         // the critic, in its own session
      say("The critic struck job 2; I'd drop it."),
    ]);
    expect((await a.ask("Is this shortlist any good?")).status).toBe("done");

    const { items } = await a.call("GET", "/agent/sessions");
    const child = items.find((s: any) => s.parent === a.session);
    expect(child).toMatchObject({ profile: "critic" });
    const childConv = (await conversationOf(a.harness, child.id, ctx))!;
    expect((await childConv.agent(ctx)).instructions).toContain("You are the Critic");

    const conv = (await conversationOf(a.harness, a.session, ctx))!;
    const result = (await conv.context(ctx)).messages.find((m: any) => m.role === "toolResult") as any;
    expect(JSON.parse(result.content[0].text).opinions).toEqual([{ profile: "critic", ok: true, answer: "Strike job 2: it's a junior role. Verdict: keep 1, strike 1" }]);
    expect((await a.call("GET", "/agent/sessions")).active).toBe(a.session);   // the council doesn't steal focus
    await a.harness.close(ctx);
  });

  it("remember writes about-me.md (with Undo), every session reads it, and notify_user fills the Inbox", async () => {
    const a = await agent("learn");
    a.faux.setResponses([
      toolUse("remember", { section: "Target", fact: "Staff ML infra roles in Bangalore or remote" }),
      toolUse("notify_user", { title: "Shortlist of 2 ready", level: "action", job_ids: [1, 2] }),
      say("Noted, and the shortlist is in your Inbox."),
    ]);
    await a.ask("I'm aiming for staff ML infra roles, Bangalore or remote.");
    const about = (await api.ui("GET", "/api/about-me")).body;
    expect(about.sections.Target).toEqual(["Staff ML infra roles in Bangalore or remote"]);
    const change = (await api.ui("GET", `/api/changes?session_id=${a.session}`)).body.changes.find((c: any) => c.entity_id === "about_me");
    expect(change).toBeTruthy();

    const inbox = (await api.ui("GET", "/api/notifications")).body;
    expect(inbox.items[0]).toMatchObject({ title: "Shortlist of 2 ready", kind: "agent", level: "action", data: { job_ids: [1, 2] } });

    const b = await agent("learn-next");
    b.faux.setResponses([say("ok")]);
    await b.ask("hi");
    const prompt = JSON.stringify((await (await conversationOf(b.harness, b.session, ctx))!.agent(ctx)).sections.map((s) => s.key));
    expect(prompt).toContain("about_the_user");
    await a.harness.close(ctx);
    await b.harness.close(ctx);
  });
});
