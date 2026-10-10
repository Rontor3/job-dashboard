# In-app agent: tailor the app by talking to it, inside the dashboard

Date: 2026-10-10 · Status: approved by user in chat (grilling session, Q1–Q30) · Supersedes the
Claude Code–driven onboarding in `INIT.md` and the inline "What does this mean?" explainer (`POST /api/explain`)

## Problem
Today, the only way to onboard and tailor the app is to open Claude Code (or another coding agent) in
this directory and follow `INIT.md`. That covers populating the profile, the question bank, preferences
and settings, and the user's history. A normal user won't do that. The in-dashboard "What does this
mean?" link gives a one-shot LLM explanation and nothing further: the user can't follow up, can't say
"then answer No for me", and can't ask for any other change.

## Goal
Any user can do everything we did in the setup sessions without leaving the dashboard:
- a persistent **Agent tab**;
- a **cursor** that turns any element into context for the agent, with an in-place **popover** for quick questions.

## Decisions

### Scope and users
- **Local, single user** (Q1). Each person runs their own copy with their own `data/`. Not hosted;
  no auth or multi-tenancy. Keep code free of single-user assumptions only where that costs nothing.
- **What the agent can change** (Q2, Q16): data, settings and app actions, **never code**.
  - **v1 tools:**
    1. Profile and identity: the application profile, the candidate profile `.local.md`, résumé upload.
    2. The question bank and Needs-you items.
    3. Preferences and agent settings.
    4. Jobs: read, status, apply details.
    5. Onboarding and setup state, including secrets.
  - **v2 tools:** queue and apply, Refresh, mail scan, hiring refresh, résumé blocks and layouts, cover letters.
- **Never allowed:** pressing Submit on an application (the existing autonomy gates stay the only path),
  reading secret values, editing code or files outside `data/`.

### Model
- v1 targets one model: the configured endpoint (`Qwen/Qwen3.8-Flash-Next-FP8` on vLLM, `/responses` with
  function calling, verified 2026-10-10) (Q6). No fallback or capability checks yet.
- **Nothing in the code is tied to one model.** The model is a per-session setting. A later phase adds
  other providers, including the user's own Claude subscription (Q6), and replaces "Claude assist"
  (`claude -p` in the apply agent) with this agent (Q25.5).

### Engine
- **Pi Durable** (`@earendil-works/pi-durable` with `pi-ai`; experimental, released 2026-10-01, version
  pinned) runs inside a **Node + Hono** service, `agent/` (Q5, Q18). It provides:
  - a checkpoint after every step, so sessions survive crashes and restarts;
  - exactly-once messages (`requestId`);
  - a per-tool replay policy (whether a tool may re-run after a crash);
  - several clients attached to one conversation.
- Every tool declares `replay: "safe"` only if it is idempotent (setting a value). Anything else
  defaults to `unsafe`.
- **Exception to the "one LLM client" rule:** agent model calls go through `pi-ai`, not `llm.py`.
  Record this in an ADR (`docs/adr/0001-in-app-agent-on-pi-durable.md`). Bulk LLM work (classify, rank,
  screen, draft) stays on `llm.py`.
- **Spike gate** (Q24). Before anything else, prove three things:
  1. `pi-ai` makes tool calls against the Qwen endpoint through `/responses`.
  2. Pi Durable's SQLite storage can live under `data/agent/`.
  3. One session streams to two browser clients at once.

  If (1) fails, write a small `pi-ai` provider adapter, then try `/chat/completions`. **Never** replace
  Pi Durable with a hand-rolled loop.
- **Spike result (2026-10-10): passed** (`docs/worklog/2026-10-10-pi-durable-spike.md`). Versions 1.1.0, no
  adapter needed. The provider's auth must return a placeholder `apiKey` for the keyless endpoint, and Node
  22.22 or newer is enough.

### Access path
- Agent tools reach data **only over HTTP to FastAPI** (Q22). The agent never opens `jobs.db` directly.
  All validation, Undo logging, confirmation gates and secret-stripping live in Python. The dashboard
  UI and the agent use the same endpoints, so the agent can do nothing the UI can't.
- Agent requests carry `X-Agent-Session` and `X-Agent-Message` headers. FastAPI uses them for the
  change log and to require confirmation tokens on consequential actions.

### Writes, Undo and confirmation (Q10, Q23)
- **Data writes apply immediately.** The thread shows a "Changed X → Y · Undo" chip.
- **`change_log` table** in `jobs.db`:
  - Columns: `id, at, actor (agent|ui), session_id, message_id, entity, entity_id, field, before, after, undone_at`.
  - Written by FastAPI for **every** write, whether from the agent or the UI. It also covers the
    candidate-profile file (full text before and after).
  - Kept forever and shown in the Memory tab as a history.
  - Undo applies `before`, and is itself logged.
- **Concurrent edits:** the last write wins, and both writes are logged.
- **Consequential actions** (v2: queue or apply, start the queue, Refresh, mail scan, autonomy, auto-submit
  and rate-limit changes, any delete) need a **Confirm / Cancel** widget. The agent can't press Confirm.
  Confirm issues a single-use token that FastAPI checks.

### Secrets and uploads (Q11)
- A **secure input** widget is a password field in the chat. The browser posts the value straight to
  `PUT /api/secrets/{KEY}`, which writes `.env`. The value never enters the model's context, the
  transcript or `change_log`, which records only "KEY set".
- The agent can check that a key is present, never its value.
- **Résumé upload** works the same way: an upload widget posts to FastAPI, which stores the file as
  `data/current_resume.pdf`. The agent is told only "résumé uploaded" and reads its text through a tool.

### Sessions and transcripts (Q8, Q9, Q12, Q13)
- **One active session** at a time. "New session" starts another. Past sessions are listed in the Agent
  tab and can be reopened.
- **One transcript per session**, kept in Pi Durable's SQLite storage at `data/agent/sessions.db`.
  There are no separate per-popover transcripts.
- **Compaction is automatic** near the model's context limit. The full transcript stays on disk.
- **No memory across sessions** beyond the user's data. The profile, bank and preferences are the
  memory; transcripts are not a second store.
- **A popover is a view into the active session, not a separate thread.** It shows only the exchanges
  started from its element (messages are tagged with that element's anchor). Clicking its header opens
  the Agent tab at that point in the session.
- **If the agent is busy,** a popover question waits its turn and the popover shows "Agent is busy with
  X; your question is next". The Agent tab has an explicit Stop button.

### Cursor (Q3, Q7, Q14, Q17)
- A cursor button in the header. **No default keyboard shortcut**; users can configure one in settings.
- **While active:** hovering outlines the element that would be captured, a click opens the popover
  anchored there, and Esc cancels. It works on every tab and in the job drawer.
- **Captured context:**
  - A **semantic anchor** when the click lands inside one. Components carry `data-agent="<kind>:<id>"`,
    e.g. `qbank:cgpa_graduation`, `job:1234`, `profile:phone`, `answer:<id>`, `resume-block:<id>`.
  - The visible text, label and nearest heading, always.
  - No screenshots, because the model is text-only.
- If the element is one the agent can't act on, it says up front that it can explain but not change it.
- **"What does this mean?"** stays, as a shortcut that opens the popover on that card with the question
  already sent. It replaces `POST /api/explain`, which is removed.

### Instructions (Q15, parked item)
- The agent's system prompt is built from:
  1. a base prompt, `docs/agent/system.md`, in the repo and adapted from `INIT.md`;
  2. the tool descriptions;
  3. a **user layer**, `data/agent/user.md`.
- The agent does not read the codebase or project docs.
- *Parked, not in this sprint:* the agent editing `data/agent/user.md`, so the user can steer its
  behaviour and workflows across sessions. The two-layer structure is built now so adding this later
  changes nothing structural.

### Onboarding (Q4)
- Setup incomplete (per `data/setup-state.md`) → a banner says "Finish setup with the agent". The user
  isn't forced to go through it.
- `INIT.md` stays the readable procedure. `docs/agent/system.md` is generated from it or kept in sync with
  it, so Claude Code and the in-app agent follow the same playbook.

### Platform (Q18–Q21, Q25–Q28, Q30)
- **Processes**, under **process-compose** (no Docker):

  | Process | What it does | Restart |
  |---|---|---|
  | `api` | FastAPI: data and actions only, stateless | on crash |
  | `worker` | apply queue runner, submit watcher, daily mail scan, embedding model; coordinates with `api` through `jobs.db` | on crash |
  | `agent` | Hono: hosts Pi Durable and serves the built frontend in production; passes `/api/*` through to `api` | on crash |
  | `browser` | the agent Chrome (port 9333, `data/browser/profile`) with the dashboard tab open | **not** restarted when the user closes it |

  Start order is gated on health checks: `api`, then `worker` and `agent`, then `browser`. In development,
  Vite serves the frontend and passes `/api` and `/agent` through. Either way the user sees one address,
  `localhost:8000`.
- **Commands:** `./jobdash start` and `./jobdash dev`, thin wrappers over process-compose.
- **Toolchain:** `mise.toml` pins Node (22.22 or newer; the packages need 22.19 or newer), Python, uv, pnpm and process-compose, installed
  inside the repo. `mise run setup` replaces `scripts/setup.sh`.
- **Repo layout:** minimal (Q21).
  - Add `agent/` (TypeScript) and `packages/agent-protocol/` (event and tool types shared with the
    frontend), with a root `pnpm-workspace.yaml`.
  - `frontend/` joins the workspace. Python stays in `src/`.
- **Language:** all new code is TypeScript (agent, protocol, cursor, popover, Agent tab). Existing JSX is
  converted gradually, not in this sprint (Q28).
- **Config** (Q30):
  - Non-secret settings (`LLM_BASE_URL`, `LLM_MODEL`, timeouts, …) move from `.env` into a **`config`**
    table in `jobs.db` that every process reads live. Secrets stay in `.env`.
  - On a change, a process reloads in place only where that's safe and costs the user nothing (e.g. the
    LLM client reads config on each call).
  - Where a reload isn't safe or would cost something (e.g. a running apply or a model download), the
    user is **notified** to restart the app or the agent. Nothing is restarted automatically in that case.

### Removed in this sprint (Q25)
- `job_dashboard/start.py`, the hand-written launcher → process-compose and `./jobdash`.
- `job_dashboard/apply/local_model.py`, which starts Ollama and quits it with `pkill -f Ollama.app` around
  the queue. Local Ollama becomes an optional process-compose entry.
- `scripts/setup.sh` → `mise run setup`.
- `POST /api/explain` and the frontend explain call → the agent.
- Update `CLAUDE.md`, `INIT.md`, `.claude/launch.json` and tests that refer to any of these.

## Testing (Q29)
- **Fast tests that never call a model** (they follow the project's fail-fast rules): a scripted fake
  model replays fixed tool calls against a temporary `jobs.db` and a temporary Pi Durable store. Assert:
  - what each tool did to the data;
  - `change_log` rows and that Undo restores the old value;
  - the agent can't press Confirm, and a missing or reused token is rejected;
  - secret values never appear in the transcript, tool results or `change_log`;
  - popover messages carry their anchor and land in the active session;
  - a crash and resume doesn't apply a write twice.
- **Opt-in live eval**, `mise run eval:agent`: about ten scenarios against the real endpoint, reporting
  pass or fail. For example: explain a Needs-you card then answer it; onboard from a résumé; fix one
  profile field; set apply details for a job; refuse to submit.

## Order of work
Each step leaves the app working, with tests green, a worklog entry and a commit.
1. **Spike** (the gate above). Throwaway code; record findings in the worklog.
2. **Platform:**
   - mise, pnpm workspace, process-compose and `./jobdash`;
   - split out the `worker`;
   - the `config` table and live reload;
   - remove the legacy launcher, `local_model`, `setup.sh`.
3. **Agent service:**
   - Hono and Pi Durable with SQLite under `data/agent/`;
   - the v1 tool set over HTTP;
   - `change_log` with Undo, the confirmation tokens, secret and upload endpoints;
   - the fake-model tests.
4. **UI:**
   - the Agent tab (sessions, stream, Undo chips, Confirm widget, secure input, upload);
   - the cursor and popover;
   - `data-agent` anchors on the main components;
   - "What does this mean?" rewired to the popover; `/api/explain` removed;
   - the onboarding banner.
5. **Live eval, ADR, docs:** `docs/agent/system.md`, `INIT.md` and `CLAUDE.md` updated.

## Open questions (later phases)
- Other providers and the user's Claude subscription. Should the agent and bulk work be able to use
  different models?
- The agent editing `data/agent/user.md`.
- v2 tools and their confirmation UX.
- Converting the rest of the frontend from JSX to TypeScript.
- Whether `config` should also absorb the `qa_store` agent settings.
