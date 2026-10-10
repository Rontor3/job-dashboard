// Slash commands, as in pi's interactive mode. The editor in the Agent tab sends `/name args`; the commands that
// need the harness run here, the rest (copy, export, hotkeys, resume, tree, new) run in the browser.
//
//   GET  /agent/commands                     every command, with prompt templates from <data>/agent/prompts/*.md
//   GET  /agent/profiles                     the agent profiles (team.ts)
//   GET  /agent/models                       the configured endpoint's models, and the app default
//   GET  /agent/sessions/:id/stats           /session
//   POST /agent/sessions/:id/command         {name, args?, at?} for name|model|thinking|compact|reload|fork|clone|<template>
//   POST /agent/sessions/:id/withdraw        {submission} take a queued message back (Alt+Up)
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { Context } from "@earendil-works/chord";
import type { Conversation, Harness } from "@earendil-works/pi-durable";
import type { CommandInfo, SessionStats } from "@jobdash/agent-protocol";
import type { Hono } from "hono";
import type { ApiClient } from "./api.ts";
import { agentDir } from "./env.ts";
import { PROVIDER, type ModelSource } from "./model.ts";
import { BASE_PROMPT, USER_PROMPT } from "./prompt.ts";
import { conversationOf, forkSession, pinModel, rename, sessionItem, setProfile } from "./sessions.ts";
import { applyProfile, findProfile, power, profiles } from "./team.ts";

export const THINKING_LEVELS = ["off", "low", "medium", "high", "xhigh"] as const;

export const BUILTIN_COMMANDS: CommandInfo[] = [
  { name: "model", description: "Select a model for this session (no argument: pick from a list)", args: "<model>", kind: "builtin" },
  { name: "thinking", description: "Set the thinking level", args: "<off|low|medium|high|xhigh>", kind: "builtin" },
  { name: "new", description: "Start a new session", kind: "builtin" },
  { name: "profile", description: "Switch this session's agent profile (no argument: list them; 'default' for the plain agent)", args: "<name>", kind: "builtin" },
  { name: "resume", description: "Resume a different session", kind: "builtin" },
  { name: "name", description: "Set the session display name, or show it", args: "<name>", kind: "builtin" },
  { name: "session", description: "Show session info and stats", kind: "builtin" },
  { name: "tree", description: "Show the session tree (forks and clones)", kind: "builtin" },
  { name: "fork", description: "Create a new session from a previous user message", kind: "builtin" },
  { name: "clone", description: "Duplicate the current session at the current position", kind: "builtin" },
  { name: "compact", description: "Manually compact the session context", args: "<instructions>", kind: "builtin" },
  { name: "reload", description: "Reload the system prompt, user instructions, tools and prompt templates", kind: "builtin" },
  { name: "copy", description: "Copy the last agent message to the clipboard", kind: "builtin" },
  { name: "export", description: "Export the session (markdown default, or: jsonl)", args: "<md|jsonl>", kind: "builtin" },
  { name: "changes", description: "Show the change log, with Undo", kind: "builtin" },
  { name: "login", description: "Set the LLM endpoint's API key", kind: "builtin" },
  { name: "settings", description: "Show the agent's settings", kind: "builtin" },
  { name: "hotkeys", description: "Show all keyboard shortcuts", kind: "builtin" },
];

export const PROMPTS_DIR = () => join(agentDir(), "prompts");

interface Template { name: string; description: string; body: string }

export function frontmatter(text: string): { meta: Record<string, string>; body: string } {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  if (!m) return { meta: {}, body: text };
  const meta = Object.fromEntries(m[1]!.split("\n").flatMap((l) => {
    const i = l.indexOf(":");
    return i > 0 ? [[l.slice(0, i).trim(), l.slice(i + 1).trim()]] : [];
  }));
  return { meta, body: text.slice(m[0].length) };
}

/** Prompt templates, pi-style: `<data>/agent/prompts/<name>.md`, optional `description:` frontmatter. */
export function templates(dir = PROMPTS_DIR()): Template[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith(".md")).sort().map((f) => {
    const { meta, body } = frontmatter(readFileSync(join(dir, f), "utf8"));
    const firstLine = body.trim().split("\n")[0] ?? "";
    return { name: basename(f, ".md"), description: meta.description ?? firstLine.slice(0, 80), body: body.trim() };
  });
}

/** `$1`…`$9`, `$@` / `$ARGUMENTS` (all arguments), as pi expands them. */
export function expand(body: string, args: string): string {
  const parts = args.trim() ? args.trim().split(/\s+/) : [];
  return body.replace(/\$(ARGUMENTS|@|[1-9])/g, (_, k: string) =>
    (k === "ARGUMENTS" || k === "@" ? args.trim() : parts[Number(k) - 1] ?? ""));
}

const empty = () => ({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0, cost: 0 });

export interface CommandDeps {
  harness: Harness;
  client: ApiClient;
  live: ModelSource;
  ctx: Context;
  /** Re-install the extension (prompt sections and tools) from disk; returns what was loaded. */
  reload?: () => Promise<string[]>;
  /** The session's conversation, configured with its model. */
  session(key: string): Promise<Conversation | undefined>;
  /** Submit user input to a session (templates). */
  submit(key: string, conv: Conversation, content: string, requestId: string): Promise<number>;
}

type Json = Record<string, unknown>;

export function installCommands(app: Hono, deps: CommandDeps): void {
  const { harness, client, live, ctx } = deps;

  app.get("/agent/commands", (c) => c.json({
    commands: [...BUILTIN_COMMANDS, ...templates().map((t): CommandInfo => ({ name: t.name, description: t.description, args: "<args>", kind: "template" }))],
  }));

  app.get("/agent/profiles", (c) => c.json({
    profiles: profiles().map(({ name, description, source, tools }) => ({ name, description, source, power: power(tools), ...(tools ? { tools } : {}) })),
  }));

  app.get("/agent/models", async (c) => {
    const current = await live.sync(client);
    return c.json({ default: current.modelId, available: (await live.available?.(client)) ?? [] });
  });

  app.get("/agent/sessions/:id/stats", async (c) => {
    const key = c.req.param("id");
    const conv = await conversationOf(harness, key, ctx);
    const item = await sessionItem(harness, key, ctx);
    if (!conv || !item) return c.json({ detail: "no such session" }, 404);
    return c.json(await stats(conv, item, deps));
  });

  app.post("/agent/sessions/:id/withdraw", async (c) => {
    const body = await c.req.json().catch(() => ({})) as { submission?: unknown };
    const conv = await conversationOf(harness, c.req.param("id"), ctx);
    const sub = conv && typeof body.submission === "number" ? await harness.submission(body.submission as never, ctx) : undefined;
    if (!sub || Number((await sub.status(ctx)).conversationId) !== Number(conv!.id)) return c.json({ detail: "no such submission" }, 404);
    return c.json({ result: await sub.abort(ctx) });
  });

  app.post("/agent/sessions/:id/command", async (c) => {
    const key = c.req.param("id");
    const body = await c.req.json().catch(() => ({})) as { name?: unknown; args?: unknown; at?: unknown; requestId?: unknown };
    const name = typeof body.name === "string" ? body.name : "";
    const args = typeof body.args === "string" ? body.args.trim().slice(0, 20_000) : "";
    const conv = await deps.session(key);
    const item = await sessionItem(harness, key, ctx);
    if (!conv || !item) return c.json({ detail: "no such session" }, 404);
    const say = (message: string, extra: Json = {}) => c.json({ ok: true, message, ...extra });
    const fail = (message: string, status: 400 | 404 | 422 = 422) => c.json({ ok: false, detail: message }, status);

    switch (name) {
      case "name": {
        if (!args) return say(`Session name: ${item.title}`);
        await rename(harness, key, args.slice(0, 120), ctx);
        return say(`Session name set: ${args.slice(0, 120)}`);
      }
      case "model": {
        if (!args) return say("", { pick: true });
        const configured = await live.sync(client);
        const target = args === "default" ? undefined : args;
        if (target) await live.offer?.(client, target);
        await pinModel(harness, key, target === configured.modelId ? undefined : target, ctx);
        await conv.configure({ model: { provider: PROVIDER, modelId: target ?? configured.modelId } }, ctx);
        return say(`Model: ${target ?? `${configured.modelId} (app default)`}`);
      }
      case "profile": {
        const list = profiles();
        if (!args) {
          const lines = list.map((p) => `- ${p.name}${item.profile === p.name ? " (current)" : ""}: ${p.description}`);
          return say(`Profiles:\n- default${item.profile ? "" : " (current)"}: the plain agent, every tool\n${lines.join("\n")}`);
        }
        const profile = args === "default" ? undefined : findProfile(args, list);
        if (args !== "default" && !profile) return fail(`No profile named ${args}. Try /profile to list them.`, 404);
        await applyProfile(conv, profile, ctx);
        await setProfile(harness, key, profile?.name, ctx);
        return say(`Profile: ${profile?.name ?? "default"}`);
      }
      case "thinking": {
        if (!args) return say(`Thinking level: ${(await conv.agent(ctx)).thinkingLevel}`);
        if (!(THINKING_LEVELS as readonly string[]).includes(args)) return fail(`Thinking level must be one of ${THINKING_LEVELS.join(", ")}`);
        await conv.configure({ thinkingLevel: args as never }, ctx);
        return say(`Thinking level: ${args}`);
      }
      case "compact": {
        await conv.compact(args || undefined, ctx);
        return say("Compacting the context…");
      }
      case "reload": {
        const loaded = (await deps.reload?.()) ?? [];
        await live.sync(client);
        return say(`Reloaded: ${loaded.join(", ") || "nothing to reload"}`);
      }
      case "fork":
      case "clone": {
        const at = typeof body.at === "number" ? body.at : (await conv.context(ctx)).entries.at(-1)?.id;
        if (at === undefined) return fail("Nothing to copy yet: the session is empty");
        const id = await forkSession(harness, key, Number(at), `${name === "fork" ? "Fork" : "Clone"} of ${item.title}`, ctx);
        return id ? say(`${name === "fork" ? "Forked" : "Cloned"} into a new session`, { session: id }) : fail("Couldn't fork", 404);
      }
      default: {
        const t = templates().find((x) => x.name === name);
        if (!t) return fail(`Unknown command: /${name}`, 404);
        const requestId = typeof body.requestId === "string" ? body.requestId : `template-${Date.now()}`;
        const submission = await deps.submit(key, conv, expand(t.body, args), requestId);
        return say("", { submission });
      }
    }
  });
}

async function stats(conv: Conversation, item: { id: string; title: string; createdAt: number; parent?: string; conversation: number }, deps: CommandDeps): Promise<SessionStats> {
  const { ctx, live } = deps;
  const view = await conv.viewState(ctx);
  const v = view.value as unknown as { entries: { kind: string; model?: { role: string; content: unknown }[] }[]; docs: Record<string, any> };
  view.dispose();
  const agent = await conv.agent(ctx);
  const messages = { user: 0, assistant: 0, toolCalls: 0, toolResults: 0 };
  for (const e of v.entries) {
    if (e.kind === "pi.user") messages.user++;
    if (e.kind === "pi.tool-result") messages.toolResults++;
    if (e.kind === "pi.assistant") {
      messages.assistant++;
      const content = e.model?.[0]?.content;
      if (Array.isArray(content)) messages.toolCalls += content.filter((b: { type?: string }) => b.type === "toolCall").length;
    }
  }
  const usage = empty();
  for (const u of Object.values((v.docs["pi.usage"]?.models ?? {}) as Record<string, any>)) {
    usage.input += u.input ?? 0;
    usage.output += u.output ?? 0;
    usage.cacheRead += u.cacheRead ?? 0;
    usage.cacheWrite += u.cacheWrite ?? 0;
    usage.total += u.totalTokens ?? 0;
    usage.cost += u.cost?.total ?? 0;
  }
  const ctxView = await conv.context(ctx);
  const contextTokens = Math.round(JSON.stringify(ctxView.messages).length / 4);      // pi's chars/4 estimate
  return {
    id: item.id, title: item.title, createdAt: item.createdAt, ...(item.parent ? { parent: item.parent } : {}),
    conversation: item.conversation,
    model: agent.model?.modelId ?? "?",
    thinkingLevel: agent.thinkingLevel,
    contextWindow: live.settings?.contextWindow ?? 0,
    contextTokens,
    entries: v.entries.length,
    messages, usage,
    tools: agent.tools.map((t) => (t as { name: string }).name),
    prompt: [BASE_PROMPT(), USER_PROMPT()].map((file) => ({ file, loaded: existsSync(file) })),
  };
}
