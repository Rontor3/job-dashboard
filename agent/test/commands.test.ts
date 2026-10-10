// Slash commands (commands.ts) on a temp store with the faux model; no FastAPI needed.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fauxAssistantMessage, fauxText } from "@earendil-works/pi-ai";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiClient } from "../src/api.ts";
import { expand } from "../src/commands.ts";
import { REPO_ROOT } from "../src/env.ts";
import { conversationOf } from "../src/sessions.ts";
import { ctx, fauxModels, openAgent, type Api } from "./fixtures.ts";

const say = (text: string) => fauxAssistantMessage([fauxText(text)]);

describe("slash commands", () => {
  let dir: string;
  let saved: string | undefined;
  beforeAll(() => {
    mkdirSync(join(REPO_ROOT, "data", "tmp"), { recursive: true });
    dir = mkdtempSync(join(REPO_ROOT, "data", "tmp", "agent-commands-"));
    saved = process.env.JOB_DASHBOARD_DATA_DIR;
    process.env.JOB_DASHBOARD_DATA_DIR = dir;
    mkdirSync(join(dir, "agent", "prompts"), { recursive: true });
    writeFileSync(join(dir, "agent", "prompts", "tailor.md"), "---\ndescription: Tailor for a job\n---\nTailor my answers for job $1. Notes: $@");
  });
  afterAll(() => {
    if (saved === undefined) delete process.env.JOB_DASHBOARD_DATA_DIR;
    else process.env.JOB_DASHBOARD_DATA_DIR = saved;
    rmSync(dir, { recursive: true, force: true });
  });

  async function agent(name: string) {
    const api = { dir, client: apiClient("http://127.0.0.1:9") } as Api;
    const { faux, source } = fauxModels();
    const { harness, app } = await openAgent(api, join(dir, `${name}.db`), source);
    const call = async (method: string, path: string, body?: unknown) => {
      const res = await app.request(path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
      return { status: res.status, body: await res.json() as any };
    };
    const session = (await call("POST", "/agent/sessions")).body.id as string;
    const command = (n: string, args = "", extra = {}) => call("POST", `/agent/sessions/${session}/command`, { name: n, args, ...extra });
    const ask = async (content: string) => {
      const { submission } = (await call("POST", `/agent/sessions/${session}/messages`, { content, requestId: `${name}-${content}` })).body;
      return (await harness.submission(submission, ctx))!.wait(ctx);
    };
    return { faux, harness, call, session, command, ask };
  }

  it("lists builtins and prompt templates", async () => {
    const a = await agent("list");
    const { commands } = (await a.call("GET", "/agent/commands")).body;
    expect(commands.map((c: any) => c.name)).toEqual(expect.arrayContaining(["model", "thinking", "compact", "fork", "reload", "tailor"]));
    expect(commands.find((c: any) => c.name === "tailor")).toMatchObject({ kind: "template", description: "Tailor for a job" });
    await a.harness.close(ctx);
  });

  it("expands a template and sends it as the user's message", async () => {
    const a = await agent("template");
    a.faux.setResponses([say("On it.")]);
    const { body } = await a.command("tailor", "42 keep it short");
    await (await a.harness.submission(body.submission, ctx))!.wait(ctx);
    expect(expand("job $1, all: $@, $3", "42 keep it")).toBe("job 42, all: 42 keep it, it");
    expect(expand("$1|$2", "only")).toBe("only|");
    const stats = (await a.call("GET", `/agent/sessions/${a.session}/stats`)).body;
    expect(stats.messages).toMatchObject({ user: 1, assistant: 1 });
    expect(stats.title).toBe("Tailor my answers for job 42. Notes: 42 keep it short".slice(0, stats.title.length));
    await a.harness.close(ctx);
  });

  it("names the session, sets thinking, and refuses a bad level", async () => {
    const a = await agent("settings");
    expect((await a.command("name", "Onboarding")).body.message).toBe("Session name set: Onboarding");
    expect((await a.command("name")).body.message).toBe("Session name: Onboarding");
    expect((await a.command("thinking", "high")).body.message).toBe("Thinking level: high");
    expect((await a.call("GET", `/agent/sessions/${a.session}/stats`)).body.thinkingLevel).toBe("high");
    expect((await a.command("thinking", "loud")).status).toBe(422);
    expect((await a.command("nope")).status).toBe(404);
    await a.harness.close(ctx);
  });

  it("clone copies the session so far into a new active session; fork stops at a message", async () => {
    const a = await agent("fork");
    a.faux.setResponses([say("one"), say("two")]);
    await a.ask("first");
    await a.ask("second");
    const clone = (await a.command("clone")).body;
    const sessions = (await a.call("GET", "/agent/sessions")).body;
    expect(sessions.active).toBe(clone.session);
    expect(sessions.items[0]).toMatchObject({ id: clone.session, parent: a.session });
    expect((await a.call("GET", `/agent/sessions/${clone.session}/stats`)).body.messages.user).toBe(2);

    const entries = (await (await conversationOf(a.harness, a.session, ctx))!.context(ctx)).entries;
    const at = entries.find((e) => e.kind === "pi.assistant")!.id;
    const fork = (await a.command("fork", "", { at })).body;
    expect((await a.call("GET", `/agent/sessions/${fork.session}/stats`)).body.messages.user).toBe(1);
    await a.harness.close(ctx);
  });
});
