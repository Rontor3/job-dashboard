# 2026-10-10 — In-app agent: design interview and spec

## Goal
Let any user onboard and tailor the app (profile, question bank, settings, history) by talking to an
agent inside the dashboard, instead of opening Claude Code in this directory. That includes a cursor
that sends any element to the agent as context.

## What changed
- Ran a requirements interview (Q1–Q30) covering stack, sessions, transcripts, access, platform and
  cleanup. Every decision is recorded in `docs/superpowers/specs/2026-10-10-in-app-agent-design.md`.
- Facts checked along the way:
  - The Qwen3.8 vLLM endpoint returns proper `function_call` output on `/responses`.
  - Pi Durable (Earendil, experimental, released 2026-10-01) is a TypeScript library that checkpoints
    every agent step, processes each message exactly once, sets a re-run-after-crash policy per tool,
    and lets several clients attach to one conversation.
  - Local Ollama's `/responses` tool calling was not tested, because Ollama wasn't running.
- No code changes.

## Key decisions
- Pi Durable in a Node + Hono service. Its tools reach data only over HTTP to FastAPI.
- process-compose runs `api`, `worker`, `agent` and `browser`; mise and pnpm workspaces for the toolchain.
- One session at a time, one transcript per session. Popovers are views into the session.
- Data writes apply immediately with Undo (a permanent `change_log`). Consequential actions need a
  Confirm the user presses. Secrets go through a secure input and never reach the model.
- A live `config` table for non-secret settings; restarts only where a reload isn't safe or would cost
  the user something.
- Removed in this sprint: the `start.py` launcher, `local_model.py`, `setup.sh` and `/api/explain`.

## Verification
Not applicable (design only). The spec's "Order of work" begins with a spike that gates the engine choice.

## Open items
- Implementation starts in a new session, beginning with the spike in step 1 of the spec.
- Later phases: other providers and the user's Claude subscription; the agent editing
  `data/agent/user.md`; v2 tools.
