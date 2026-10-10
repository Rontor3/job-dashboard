// Agent profiles and the council (spec: docs/superpowers/specs/2026-10-10-agent-first-overhaul-design.md).
//
// A profile is a system prompt and a tool set for one kind of work: the Scout builds shortlists, the Critic reviews
// as a skeptical hiring manager, the Advocate makes the strongest honest case. The base profiles live in
// docs/agent/profiles/*.md; the user's own (or overrides, by name) in <data>/agent/profiles/*.md. A profile's body
// becomes the session's `instructions` (rendered after the playbook) and its `tools:` line filters the tools.
//
// The council: one agent asks others for their view. `consult_agents` starts a child session per profile, sends each
// the same brief, waits for them in parallel and returns their answers. Each child is an ordinary session (parent =
// the asker), so the user can open it and read how it got there.
import { randomUUID } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { Context } from "@earendil-works/chord";
import type { Conversation, Harness } from "@earendil-works/pi-durable";
import type { ProfileInfo } from "@jobdash/agent-protocol";
import type { ApiClient } from "./api.ts";
import { frontmatter } from "./commands.ts";
import { agentDir, REPO_ROOT } from "./env.ts";
import type { ModelSource } from "./model.ts";
import { conversationOf, createSession } from "./sessions.ts";

export interface Profile extends ProfileInfo { body: string; tools?: string[] }

export const BASE_PROFILES = () => join(REPO_ROOT, "docs", "agent", "profiles");
export const USER_PROFILES = () => join(agentDir(), "profiles");

function load(dir: string, source: "base" | "user"): Profile[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith(".md")).sort().map((f) => {
    const { meta, body } = frontmatter(readFileSync(join(dir, f), "utf8"));
    const tools = meta.tools?.split(",").map((t) => t.trim()).filter(Boolean);
    return { name: basename(f, ".md"), description: meta.description ?? "", source, body: body.trim(), ...(tools?.length ? { tools } : {}) };
  });
}

/** Every profile; a user profile replaces a base one of the same name. */
export function profiles(base = BASE_PROFILES(), user = USER_PROFILES()): Profile[] {
  const byName = new Map<string, Profile>();
  for (const p of [...load(base, "base"), ...load(user, "user")]) byName.set(p.name, p);
  return [...byName.values()];
}

const WRITES = /^(update_|set_|add_|remove_|write_|remember|undo_change|answer_|review_guess|request_|dismiss_|notify_)/;

/** How far a profile reaches, in the user's terms (shown before they pick one). */
export function power(tools: string[] | undefined): "read" | "write" | "act" {
  if (!tools || tools.includes("propose_action")) return "act";
  return tools.some((t) => WRITES.test(t)) ? "write" : "read";
}

export const findProfile = (name: string, list = profiles()) => list.find((p) => p.name === name);

/** Put a session on a profile (undefined: back to the plain playbook with every tool). */
export async function applyProfile(conv: Conversation, profile: Profile | undefined, ctx: Context): Promise<void> {
  await conv.configure({
    instructions: profile ? profile.body : null,
    tools: profile?.tools ? profile.tools.map((name) => ({ name }) as never) : null,
  }, ctx);
}

export interface Opinion { profile: string; session: string; answer: string; ok: boolean }

/** What a tool needs to run the council: filled in once the harness is open (tools are built before it). */
export interface Team {
  consult?: (parent: string, brief: string, names: string[]) => Promise<Opinion[]>;
}

const COUNCIL_TIMEOUT_MS = 5 * 60_000;

function lastText(messages: readonly unknown[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] as { role?: string; content?: unknown };
    if (m.role !== "assistant") continue;
    const text = Array.isArray(m.content)
      ? m.content.filter((b: { type?: string }) => b.type === "text").map((b: { text: string }) => b.text).join("\n")
      : typeof m.content === "string" ? m.content : "";
    if (text.trim()) return text.trim();
  }
  return "";
}

export function makeConsult(harness: Harness, client: ApiClient, live: ModelSource, ctx: Context, timeoutMs = COUNCIL_TIMEOUT_MS): Team["consult"] {
  return async (parent, brief, names) => {
    const model = await live.sync(client);
    const list = profiles();
    return Promise.all(names.map(async (name): Promise<Opinion> => {
      const profile = findProfile(name, list);
      if (!profile) return { profile: name, session: "", answer: `No profile named ${name}.`, ok: false };
      const key = await createSession(harness, model, ctx, {
        activate: false, parent, profile: name, title: `${name[0]!.toUpperCase()}${name.slice(1)}: ${brief.replace(/\s+/g, " ").slice(0, 50)}`,
      });
      const conv = (await conversationOf(harness, key, ctx))!;
      await applyProfile(conv, profile, ctx);
      const sub = await conv.submit({ type: "input", content: brief, requestId: randomUUID() }, ctx);
      let timer: NodeJS.Timeout | undefined;
      const timedOut = new Promise<"timeout">((r) => { timer = setTimeout(() => r("timeout"), timeoutMs); });
      const settled = await Promise.race([sub.wait(ctx), timedOut]);
      clearTimeout(timer);
      if (settled === "timeout") {
        await conv.abort(ctx);
        return { profile: name, session: key, answer: "Ran out of time before answering.", ok: false };
      }
      const answer = lastText((await conv.context(ctx)).messages);
      return { profile: name, session: key, answer: answer || "Gave no answer.", ok: !!answer };
    }));
  };
}
