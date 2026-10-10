# 0001 — The in-app agent runs on Pi Durable, outside `llm.py`

- **Status:** accepted, 2026-10-10
- **Spec:** `docs/superpowers/specs/2026-10-10-in-app-agent-design.md`
- **Spike:** `docs/worklog/2026-10-10-pi-durable-spike.md`

## Context

Onboarding and "What does this mean?" used to live in two places:
- onboarding was a Claude Code session following `INIT.md`;
- "What does this mean?" was a one-shot `POST /api/explain`.

The dashboard needs one agent that can do more:
- talk about anything on the page;
- change the user's data with Undo;
- ask for secrets and the résumé without seeing them;
- wait for a Confirm before anything consequential;
- survive a restart in the middle of a run.

That is a durable, tool-calling conversation loop that several browser tabs watch at once.

The repo rule is **one LLM client**: every model call goes through `job_dashboard/llm.py`. `llm.py` is a request
helper for bulk work (classify, rank, screen, draft). It has none of the following:
- a conversation store;
- checkpoints;
- a tool-replay policy;
- streaming to several clients.

Building those in Python would mean writing an agent loop by hand.

## Decision

- **Engine and service.** The in-app agent is a separate Node service, `agent/`: Hono, with Pi Durable
  (`@earendil-works/pi-durable` 1.1.0 plus `pi-ai`, pinned).
- **Storage.** Sessions are stored in SQLite at `data/agent/sessions.db`.
- **Model calls.** Its calls go through `pi-ai`'s OpenAI Responses provider. This is an **explicit exception to the
  one-LLM-client rule.**
- **What stays the same:**
  - **One endpoint.** The agent uses the same `LLM_BASE_URL` / `LLM_MODEL` from the config table and the same
    `LLM_API_KEY` from `.env`. Changing the model changes it for both.
  - **One data path.** The agent never opens `jobs.db` or the data files. Every read and write is an HTTP call to
    FastAPI, so it shares the dashboard's validation. Writes land in the change log (with Undo) and in the
    confirmation-token gate.
  - **Bulk LLM work stays on `llm.py`.** This includes classify, rank, screen, draft, mail and hiring.
- **Replay.** A tool is `replay: "safe"` only when it only sets a value, so re-running it after a crash is harmless.
  Everything else is `unsafe`: Pi Durable won't re-run it blindly.
- **Fallbacks if Pi Durable falls short:**
  - write a small `pi-ai` provider adapter, or fall back to `/chat/completions`;
  - never replace Pi Durable with a hand-rolled loop.

## Consequences

- A second runtime: Node 22, pinned by mise, workspace-installed by pnpm. `./jobdash setup` covers it.
- **Ports.** The agent process serves the dashboard on :8000 and passes `/api` through to FastAPI, which moves to
  :8001.
- **Experimental dependency.** Pi Durable was released 2026-10-01. Its version is pinned and upgraded on purpose.
- **Tests.** The fake-model tests (`agent/test/`) pin the contract: crash and resume, exactly-once, secrets never in
  the transcript, Undo, and confirmation tokens.
- **Live checks.** The live eval (`mise run eval:agent`) checks behaviour on the real model.
- **Model failures.** They show up in two places:
  - for the agent, as a failed run in the thread;
  - for everything else, through `llm.py` as before.
