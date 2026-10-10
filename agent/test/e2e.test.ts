// The spec's fast tests (Q29): a scripted fake model replays fixed tool calls against a temp jobs.db (a real FastAPI)
// and a temp Pi Durable store. No real model, no user data.
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { parseElementMessage } from "@jobdash/agent-protocol";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { conversationOf } from "../src/sessions.ts";
import { ctx, fauxModels, hasPython, openAgent, startApi, type Api } from "./fixtures.ts";

const toolUse = (name: string, args: Parameters<typeof fauxToolCall>[1]) =>
  fauxAssistantMessage([fauxToolCall(name, args)], { stopReason: "toolUse" });
const say = (text: string) => fauxAssistantMessage([fauxText(text)]);

describe.skipIf(!hasPython)("agent over FastAPI", () => {
  let api: Api;
  let entry: string;
  beforeAll(async () => {
    api = await startApi();
    entry = (await api.ui("GET", "/api/answers")).body.answers[0].id;
  }, 30_000);
  afterAll(() => api?.stop());

  async function agent(name: string) {
    const { faux, source } = fauxModels();
    const { harness, app } = await openAgent(api, join(api.dir, `${name}.db`), source);
    const post = async (path: string, body?: unknown) => {
      const res = await app.request(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
      return res.json() as Promise<any>;
    };
    const session = (await post("/agent/sessions")).id as string;
    let n = 0;
    const ask = async (content: string, context?: unknown) => {
      const { submission } = await post(`/agent/sessions/${session}/messages`, { content, requestId: `${name}-${++n}`, context });
      return (await harness.submission(submission, ctx))!.wait(ctx);
    };
    const entries = async () => {
      const view = await (await conversationOf(harness, session, ctx))!.viewState(ctx);
      const out = view.value.entries;
      view.dispose();
      return out as any[];
    };
    return { faux, harness, app, session, ask, entries, post };
  }

  it("writes through FastAPI, logs the change with the session and call ids, and Undo restores it", async () => {
    const a = await agent("write");
    a.faux.setResponses([toolUse("set_answer", { entry_id: entry, answer: "Yes" }), say("Saved.")]);
    expect((await a.ask("Answer yes to that")).status).toBe("done");

    const rows = (await api.ui("GET", `/api/changes?session_id=${a.session}`)).body.changes;
    expect(rows).toHaveLength(1);
    const call = (await a.entries()).find((e) => e.kind === "pi.assistant")!.model[0].content.find((b: any) => b.type === "toolCall");
    expect(rows[0]).toMatchObject({ actor: "agent", entity: "qbank", entity_id: entry, field: "answer", after: "Yes", message_id: call.id });

    const result = (await a.entries()).find((e) => e.kind === "pi.tool-result")!.model[0];
    expect(result.details.changes[0].id).toBe(rows[0].id);                  // what the Undo chip uses

    expect((await api.ui("POST", `/api/changes/${rows[0].id}/undo`)).status).toBe(200);
    const after = (await api.ui("GET", "/api/answers")).body.answers.find((x: any) => x.id === entry);
    expect(after.answer).toBe(rows[0].before);
    await a.harness.close(ctx);
  });

  it("a widget tool ends the run; the secret's value never reaches the transcript, a tool result or the log", async () => {
    const a = await agent("secret");
    a.faux.setResponses([toolUse("request_secret", { key: "TINYFISH_API_KEY", reason: "company research" }), say("never used")]);
    await a.ask("Set up company research");
    expect(a.faux.getPendingResponseCount()).toBe(1);                       // stopped without asking the model again

    expect((await api.ui("PUT", "/api/secrets/TINYFISH_API_KEY", { value: "tf-SECRET-e2e" })).status).toBe(200);
    a.faux.setResponses([toolUse("get_setup_state", {}), say("It's set.")]);
    await a.ask("[I set TINYFISH_API_KEY]");
    const transcript = JSON.stringify(await a.entries());
    expect(transcript).toContain('\\"TINYFISH_API_KEY\\":true');
    expect(transcript).not.toContain("tf-SECRET-e2e");
    expect(JSON.stringify((await api.ui("GET", "/api/changes")).body)).not.toContain("tf-SECRET-e2e");
    await a.harness.close(ctx);
  });

  it("the agent can't press Confirm; the human's token lets the action through once", async () => {
    const a = await agent("confirm");
    const path = `/api/answers?entry_id=${entry}`;
    a.faux.setResponses([toolUse("propose_action", { method: "DELETE", path, summary: "Retire this answer" })]);
    await a.ask("Delete that answer");
    const [pending] = (await api.ui("GET", `/api/confirmations?session_id=${a.session}&status=pending`)).body.confirmations;
    expect(pending).toMatchObject({ method: "DELETE", path, summary: "Retire this answer" });

    const asAgent = { session: a.session, message: "m" };
    expect((await api.client.call("POST", `/api/confirmations/${pending.id}/confirm`, asAgent)).status).toBe(403);
    expect((await api.client.call("DELETE", path, asAgent)).status).toBe(403);           // no token

    const { token } = (await api.ui("POST", `/api/confirmations/${pending.id}/confirm`)).body;
    expect((await api.client.call("DELETE", path, { ...asAgent, confirmToken: token })).status).toBe(200);
    expect((await api.client.call("DELETE", path, { ...asAgent, confirmToken: token })).status).toBe(403);   // used up
    await api.ui("POST", `/api/changes/${(await api.ui("GET", "/api/changes")).body.changes[0].id}/undo`);
    await a.harness.close(ctx);
  });

  it("a popover question carries its element's anchor and lands in the active session", async () => {
    const a = await agent("popover");
    a.faux.setResponses([say("It asks for your graduation CGPA.")]);
    await a.ask("What does this mean?", { anchor: `qbank:${entry}`, text: "CGPA at graduation", heading: "Needs you" });
    const user = (await a.entries()).find((e) => e.kind === "pi.user")!.model[0];
    const text = typeof user.content === "string" ? user.content : user.content[0].text;
    expect(parseElementMessage(text)).toMatchObject({ context: { anchor: `qbank:${entry}`, heading: "Needs you" }, question: "What does this mean?" });
    const sessions = await (await a.app.request("/agent/sessions")).json() as any;
    expect(sessions.active).toBe(a.session);
    expect(sessions.items[0]).toMatchObject({ id: a.session, title: "What does this mean?" });
    await a.harness.close(ctx);
  });

  it("read-only status tools report the queue, tracker and a job's last run without logging anything", async () => {
    const a = await agent("status");
    a.faux.setResponses([toolUse("get_overview", {}), toolUse("get_tracker", {}), toolUse("get_apply_run", { job_id: 1 }), say("Idle.")]);
    await a.ask("What's going on?");
    const results = (await a.entries()).filter((e) => e.kind === "pi.tool-result").map((e) => e.model[0]);
    expect(results.map((r: any) => r.isError)).toEqual([false, false, true]);         // job 1 was never run
    expect(JSON.parse(results[2].content[0].text)).toMatchObject({ error: 404 });
    const overview = JSON.parse(results[0].content[0].text);
    expect(overview).toMatchObject({ jobs: { total: 1 }, queue: { items: [] }, refresh: { running: false } });
    expect(Object.keys(overview.browser_sites)).toContain("linkedin");
    expect(JSON.parse(results[1].content[0].text)).toHaveProperty("applied");
    expect((await api.ui("GET", `/api/changes?session_id=${a.session}`)).body.changes).toHaveLength(0);
    await a.harness.close(ctx);
  });

  it("builds the essay ingredient bank, each write undoable", async () => {
    const a = await agent("ingredients");
    const unit = { type: "project", title: "Churn model", org: "Acme", source: "Built a churn model (AUC 0.91).", tech: ["XGBoost"] };
    a.faux.setResponses([toolUse("add_ingredient", unit), toolUse("update_ingredient", { id: "churn-model", impact: ["AUC 0.91"] }),
      toolUse("get_ingredients", {}), say("Added.")]);
    await a.ask("Build my ingredient bank");
    const results = (await a.entries()).filter((e) => e.kind === "pi.tool-result").map((e) => e.model[0]);
    expect(results.map((r: any) => r.isError)).toEqual([false, false, false]);
    expect(JSON.parse(results[2].content[0].text).units).toEqual([expect.objectContaining({ id: "churn-model", impact: ["AUC 0.91"], tech: ["XGBoost"] })]);
    const changes = (await api.ui("GET", `/api/changes?session_id=${a.session}`)).body.changes;
    expect(changes.map((c: any) => [c.entity, c.entity_id, c.undoable])).toEqual([["file", "ingredients", true], ["file", "ingredients", true]]);
    await a.harness.close(ctx);
  });

  it("streams a snapshot first to every client of a session", async () => {
    const a = await agent("stream");
    const read = async () => {
      const res = await a.app.request(`/agent/sessions/${a.session}/events`);
      const reader = res.body!.getReader();
      const { value } = await reader.read();
      await reader.cancel();
      return new TextDecoder().decode(value);
    };
    const [one, two] = await Promise.all([read(), read()]);
    for (const chunk of [one, two]) expect(chunk).toMatch(/^event: agent\ndata: \{"type":"snapshot"/);
    await a.harness.close(ctx);
  });

  it("a crash inside a write tool, then resume, applies the write once", async () => {
    const db = join(api.dir, "crash.db");
    const child = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", join(import.meta.dirname, "crash-child.ts"), db, api.url, entry],
      { encoding: "utf8", timeout: 20_000 });
    expect(child.status).toBe(137);
    const session = child.stdout.trim();
    expect((await api.ui("GET", `/api/changes?session_id=${session}`)).body.changes).toHaveLength(1);   // the write landed

    const { faux, source } = fauxModels();
    faux.setResponses([say("Saved.")]);
    const { harness } = await openAgent(api, db, source);
    const conv = (await harness.conversation(Number(session.replace("conversation-", "")) as never, ctx))!;
    const settled = await (await conv.submit({ type: "input", content: "Save 8.30/10 as my CGPA answer.", requestId: "crash-1" }, ctx)).wait(ctx);
    expect(settled.status).toBe("done");                                      // same requestId: the original run, finished
    const rows = (await api.ui("GET", `/api/changes?session_id=${session}`)).body.changes;
    expect(rows).toHaveLength(1);                                             // the rerun wrote the same value: nothing new
    expect((await api.ui("GET", "/api/answers")).body.answers.find((x: any) => x.id === entry).answer).toBe("8.30/10");
    await harness.close(ctx);
  }, 30_000);
});
