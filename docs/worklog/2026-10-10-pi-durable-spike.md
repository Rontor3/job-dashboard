# 2026-10-10 — Spike: Pi Durable on the Qwen endpoint (in-app agent, step 1)

## Goal
Step 1 of `docs/superpowers/specs/2026-10-10-in-app-agent-design.md` gates the engine choice. It must prove:
1. `pi-ai` makes tool calls against the Qwen3.8 endpoint.
2. Pi Durable's SQLite storage can live under `data/`.
3. One session can stream to two browser clients at once.

## Result: all three pass, plus a crash-and-resume check. Pi Durable stays; no adapter needed.

| Check | Outcome |
|---|---|
| 1. Tool calls via `/responses` | `createProvider()` with `openAIResponsesApi()` and `baseUrl` = `LLM_BASE_URL`. The raw call returned `stopReason: toolUse`. |
| 2. Durable run on SQLite under `data/` | A full harness run made the correct calls (`get_profile_field(cgpa)`, then `set_bank_answer(cgpa_graduation=8.30/10)`) and settled `done` in about 7 s. Transcript: `pi.user, pi.system, pi.assistant, pi.tool-result ×2, pi.assistant ×2`. Nothing was written to `~` (checked for `~/.pi` and similar). |
| 3. Two clients, one session | A Hono route `/agent/events` (`streamSSE` + `watchEvents`) and `POST /agent/message`. Two HTTP clients ("popover" and "agent tab") each received the same 26 events in the same order: a snapshot, then message, tool, run and usage events. |
| Crash and resume | The process was killed inside a `replay: "safe"` write tool. On reopen, resubmitting the same `requestId` reused the original submission (one `pi.user` entry). The tool re-ran once and the final state was correct, with one `pi.tool-result`. |

## Findings for the implementation
- **Versions:** `@earendil-works/pi-durable`, `pi-ai` and `chord` are all at **1.1.0** (published 2026-10-07).
  `engines.node >= 22.19`, so the installed Node 22.22.2 works. The spec's "22.23 or newer" requirement only
  applies to running the package's `.ts` sources, which we don't do. Pin Node 22.22 or newer in `mise.toml`.
  Use `hono@4.13.13` and `@hono/node-server@2.1.4`.
- **Keyless endpoint quirk:** the Responses implementation requires *some* API key. The auth resolver must
  return `{ auth: { apiKey: LLM_API_KEY || "unused" } }`; `{ auth: {} }` fails with
  "No API key for provider".
- **Thinking output:** Qwen returns reasoning content even with `reasoning: false` on the model definition.
  pi-ai surfaces it as `thinking` blocks. The UI should collapse or hide these. Consider `reasoning: true`
  and a `thinkingLevel` setting.
- **Node's SQLite** (`node:sqlite`) prints an `ExperimentalWarning` on Node 22. It's harmless; suppress it
  in the agent process.
- **Useful building blocks**, all confirmed in the 1.1.0 README:
  - the faux provider (`fauxProvider()`, `fauxToolCall`) for the fake-model tests;
  - `hook(ToolTask, { beforeTool })` to block tools, e.g. Submit;
  - `whenBusy: "follow-up"`, the default, which matches the spec's queued popover questions;
  - `root.abort()` for the Stop button;
  - automatic compaction settings;
  - `configure({ model })` for a per-session model.
- **One process owns a storage file** (no cross-process locking). Only the `agent` process may open
  `data/agent/sessions.db`. This matches the spec.

## Verification
The spike code is under `data/spikes/pi-durable/` (gitignored, throwaway). It contains `provider.ts`,
`spike1.ts` (checks 1–2), `spike3.ts` (two-client SSE) and `spike2.ts` (run `crash`, then `resume`).
Run each with `node <file>` from that directory, after `npm install` with
`npm_config_cache=data/cache/npm`.

## Open items
- Step 2 (Platform) starts in a new session.
