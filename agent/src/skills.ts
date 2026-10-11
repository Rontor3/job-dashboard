// Skills: instruction packs the agent loads when a task needs them (spec 2026-10-11-agent-driven-apply-design.md).
// Base skills live in docs/agent/skills/*.md; the user's own (or overrides, by name) in <data>/agent/skills/*.md.
// The system prompt lists only each skill's name and description; `load_skill` returns the body, so a long
// procedure costs context only in the sessions that use it.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { section } from "@earendil-works/pi-durable";
import { frontmatter } from "./commands.ts";
import { agentDir, REPO_ROOT } from "./env.ts";

export interface Skill { name: string; description: string; body: string }

export const BASE_SKILLS = () => join(REPO_ROOT, "docs", "agent", "skills");
export const USER_SKILLS = () => join(agentDir(), "skills");

function load(dir: string): Skill[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith(".md")).sort().map((f) => {
    const { meta, body } = frontmatter(readFileSync(join(dir, f), "utf8"));
    return { name: basename(f, ".md"), description: meta.description ?? "", body: body.trim() };
  });
}

/** Every skill; a user skill replaces a base one of the same name. */
export function skills(base = BASE_SKILLS(), user = USER_SKILLS()): Skill[] {
  const byName = new Map<string, Skill>();
  for (const s of [...load(base), ...load(user)]) byName.set(s.name, s);
  return [...byName.values()];
}

export const skillsSection = () => section("skills", () => {
  const list = skills();
  if (!list.length) return undefined;
  return "Skills you can load with `load_skill` when a task needs one (read the whole skill before starting):\n"
    + list.map((s) => `- ${s.name}: ${s.description}`).join("\n");
});
