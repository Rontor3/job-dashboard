// The system prompt, in two layers (spec, Instructions): the base playbook in the repo (docs/agent/system.md, kept
// in step with INIT.md) and the user's own layer (data/agent/user.md). The agent never reads the codebase. Both
// files are re-read when they change, so editing either applies to the next request without a restart.
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { section } from "@earendil-works/pi-durable";
import { agentDir, REPO_ROOT } from "./env.ts";

export const BASE_PROMPT = () => join(REPO_ROOT, "docs", "agent", "system.md");
export const USER_PROMPT = () => join(agentDir(), "user.md");

const cache = new Map<string, { mtime: number; text: string }>();

export const clearPromptCache = () => cache.clear();

function readCached(path: string): string | undefined {
  if (!existsSync(path)) return undefined;
  const mtime = statSync(path).mtimeMs;
  const hit = cache.get(path);
  if (hit && hit.mtime === mtime) return hit.text;
  const text = readFileSync(path, "utf8").trim();
  cache.set(path, { mtime, text });
  return text || undefined;
}

export const sections = (base = BASE_PROMPT, user = USER_PROMPT) => [
  section("playbook", () => readCached(base()) ?? "You help the user set up and tailor their job-application agent.", { tag: false }),
  section("user_instructions", () => readCached(user())),
];
