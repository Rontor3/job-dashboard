// Where the agent reads and writes: the repo's .env (read fresh, so a key set from the dashboard applies at once)
// and the data root, the same one job_dashboard/paths.py uses. The agent writes only under <data>/agent/.
import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO_ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));

export function readEnvFile(path = join(REPO_ROOT, ".env")): Record<string, string> {
  if (!existsSync(path)) return {};
  const out: Record<string, string> = {};
  for (const raw of readFileSync(path, "utf8").split("\n")) {
    const line = raw.trim().replace(/^export\s+/, "");
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    let value = line.slice(eq + 1).trim();
    if (value.length >= 2 && value[0] === value.at(-1) && (value[0] === '"' || value[0] === "'")) value = value.slice(1, -1);
    out[line.slice(0, eq).trim()] = value;
  }
  return out;
}

/** A setting from the environment, else the .env file. */
export const setting = (key: string): string | undefined => process.env[key] || readEnvFile()[key] || undefined;

export function dataDir(): string {
  const raw = setting("JOB_DASHBOARD_DATA_DIR");
  if (!raw) return join(REPO_ROOT, "data");
  return isAbsolute(raw) ? raw : resolve(REPO_ROOT, raw);
}

export const agentDir = () => join(dataDir(), "agent");
