# 0002 — The in-app agent owns apply runs; the Python engine becomes its tools

- **Status:** accepted, 2026-10-11
- **Spec:** `docs/superpowers/specs/2026-10-11-agent-driven-apply-design.md`

## Context

Applications are filled by `career_agent`: a LangGraph walk for career sites and a board loop for LinkedIn, Wellfound
and similar boards. Both are fixed loops. When the loop meets something it can't handle, the run stops, and the
in-app agent only finds out afterwards, from the Inbox.

The user wants the agent to reason through every step instead. That means:
- reading a DOM-first view of the form;
- deciding values grounded in stored sources;
- having a script fill and verify them;
- pausing with a clear status when it can't answer.

## Decision

- The agent drives the run through tools that call FastAPI routes, as its other tools do. So every change goes into
  the existing Undo log, and every route enforces its own gates.
- The live Playwright page is held by a Python apply-session service in the API process. The service runs on one
  dedicated browser thread, because sync Playwright is bound to its thread. It attaches to the one agent Chrome.
- The existing perception, filler, board-driver, gate-probe and autonomy code is reused as tool steps. `run_board`
  is split into steps that the CLI loop and the service both call.
- `apply_submit` is gated server-side by `autonomy.autosubmit_policy` plus a priority hold. The agent can't reach a
  submit the user hasn't durably authorized.

## Consequences

- There are two engines (`apply_engine=script|agent`) until the agent engine is verified; then script becomes the fallback.
- Live pages don't survive an API restart. Reattaching is best-effort, and otherwise a resume starts on a fresh page from saved answers.
- How good a run is depends on how well the configured model calls tools. The tools keep payloads small (short
  ids, capped options, precomputed suggestions) to help.
