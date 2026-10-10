# 2026-10-10 — In-app agent (spec steps 3–5)

## Goal
Steps 3–5 of `docs/superpowers/specs/2026-10-10-in-app-agent-design.md`:
- **3, agent service:** the agent service, the v1 tools, the change log with Undo, confirmation tokens, and the
  secret and upload endpoints.
- **4, UI:** the dashboard UI (Agent tab, cursor, popover, anchors, onboarding banner).
- **5, docs:** the live eval, the ADR and the docs.

## Step 3: agent service
- **Change log (`job_dashboard/changes.py`, `change_entities.py`, `api/change_routes.py`).** A pure ASGI middleware
  wraps every `/api` request. It:
  - binds the actor: `X-Agent-Session` / `X-Agent-Message` mean the agent, anything else is the UI;
  - refuses agent requests to human-only routes (Confirm, secret values, résumé upload);
  - checks confirmation tokens on consequential routes;
  - returns the rows a request logged in `X-Changes`, which the agent's Undo chips use;
  - logs any other successful write as an action that can't be undone, so the history is complete.

  Field writes go through `changes.apply(entity, id, field, value)`, which reads `before`, writes and logs.
  `undo` writes `before` back through the same writer and is logged itself. Entities: profile field, bank entry
  answer/status, application question row, agent setting, config key, job status/apply details, and whole files
  (the candidate profile `.local.md`, `setup-state.md`). Existing routes now write through it: application profile,
  answers, Needs-you reply/edit, agent and queue settings, auto-submit, job status, apply details, config.
- **Confirmation (`job_dashboard/confirm.py`).**
  - Consequential routes: queue/apply, start the queue, Refresh, mail scan, hiring refresh, reconcile, auto-submit,
    queue settings, and any DELETE.
  - The agent proposes the exact request. The human's Confirm (refused from the agent) issues a single-use token
    bound to that method, path, query and body.
- **Setup routes (`api/setup_routes.py`).**
  - `/api/secrets`: presence only; `PUT` writes `.env` and is refused from the agent. The log says only "set".
  - `PUT /api/current-resume`: a PDF body; refused from the agent.
  - `GET /api/current-resume/text`.
  - `GET/PUT /api/candidate-profile` and `/api/setup-state`, both logged with Undo.
- `POST /api/explain` is removed; the agent answers instead.
- **Agent service (`agent/`, TypeScript, run by Node's type stripping, no build step).**
  - Pi Durable 1.1.0 on SQLite at `data/agent/sessions.db`, behind Hono on :8000. It serves the built UI and passes
    `/api` through to FastAPI, which moves to :8001.
  - Sessions are conversations with a UUID key in a session-scoped doc. Conversation ids are small per-store
    integers and would collide in the change log if the store were ever recreated.
  - 25 v1 tools over HTTP. Only value-setting tools are `replay: "safe"`.
  - Widget tools (`request_secret`, `request_resume_upload`, `propose_action`) end the run.
  - The model comes from the config table and is rebuilt when it changes. The API key is read from `.env` on each
    request.
  - System prompt: `docs/agent/system.md` (adapted from `INIT.md`) plus `data/agent/user.md`.
  - `packages/agent-protocol` holds what the service and the dashboard share: element-context encoding (the anchor
    travels inside the user message), session types, widget tool names.
- New config key `LLM_CONTEXT_WINDOW`. `JOB_DASHBOARD_ENV_FILE` points the secrets route elsewhere, for tests.
- process-compose: `api` :8001 → `agent` :8000 (health-gated) → `browser`. Dev mode: Vite :8000 → api :8001 and
  agent :8002.

### Verification
- `tests/test_change_log.py` (12): UI vs agent actor, Undo for every entity, no-op writes not logged, actions not
  undoable, secrets never in the log or responses, human-only upload and secrets, confirmation tokens (agent can't
  confirm, wrong request, reuse, cancel).
- `agent/test/e2e.test.ts` (6) runs a real FastAPI (`tests/agent_api_app.py`) on a temp data root, with the faux
  model and a temp SQLite store. It checks:
  - a write is logged with the session and tool-call ids, and Undo restores it;
  - widget tools end the run;
  - a secret's value is never in the transcript or the log;
  - the agent can't confirm, and a token works once;
  - a popover message carries its anchor into the active session;
  - two SSE clients both get the snapshot;
  - a crash inside a write tool (child process exits 137), then resume, writes once.

  2.4 s. `agent/test/protocol.test.ts` (3) covers encoding, including page text that tries to close the element
  block early.
- Live run of `./jobdash start`: every process healthy. On the real Qwen endpoint the agent called
  `list_needs_you` and answered.

## Step 4: UI
- **`frontend/src/agent/` (TypeScript, typechecked with `tsc --noEmit`; the rest of the frontend stays JS).**
  - `AgentProvider`: one SSE connection to the active session, shared by the Agent tab and every popover. It also
    holds the cursor mode and the open popover.
  - `state.ts`: a pure reducer from the service's events (snapshot, streamed message updates, entries, tools, inbox)
    to a thread. `exchangesFor` picks the exchanges started from one anchor; `busyWith` names the running question.
  - `Thread`: messages, thinking folded away, "Using …" for tool calls, a "Changed X: a → b · Undo" chip per logged
    change, and the widgets.
  - `Widgets`: secret input, résumé upload and Confirm/Cancel each talk straight to FastAPI and tell the agent only
    the outcome (`[I set KEY]`, `Confirmed: … It's done.`). The secret value never reaches the agent.
  - `AgentTab`: sessions, New session, starter chips, Stop, composer. `ChangeHistory` is Memory → History, with Undo.
  - `Cursor`: the "Ask about…" header button turns it on; hover outlines what a click captures; click opens the
    popover; Esc cancels. `capture.ts` takes the nearest `data-agent` anchor plus visible text, label, heading, tab.
  - `Popover`: in place, clamped to the viewport, showing only this element's exchanges. It says when the agent
    can only explain (no actionable anchor) and when the question is queued behind another.
  - `SetupBanner`: while `setup-state.md` is missing or not complete, offers "Finish setup with the agent".
- `data-agent` anchors: job rows, the tracker and the job drawer (`job:<id>`); Answers entries (`profile:<ref>` /
  `qbank:<id>`); thresholds and browser sources (`setting:…`); Needs-you cards (`question:`, `answer:`, `qbank:`).
- Needs-you "What does this mean?" now opens the popover and asks there. `explainQuestion` is gone from `api.js`.
- The topbar shows an alert when the worker is down.
- `mise run test` now typechecks the frontend too.

### Verification
- New tests:
  - `agent_state.test.ts`: the reducer, popover filtering, the busy question, capture.
  - `agent_ui.test.jsx`, covering:
    - the Undo chip;
    - the secret value never sent to `/agent`;
    - Confirm runs the exact request with the token, and Cancel never runs it;
    - the setup banner;
    - History with Undo.
- `inbox.test.jsx` checks that "What does this mean?" opens the popover and sends the anchor and text, and that
  the link is absent without the agent.
- Frontend: 25 files / 139 tests pass; `tsc --noEmit` is clean.
- In the browser, on `./jobdash start` with the real model:
  - "What does this mean?" on a Needs-you card opened the popover, and the answer streamed in.
  - The Agent tab shows that exchange with its "About:" line next to the earlier session messages.
  - The setup banner shows on a setup that isn't complete.
