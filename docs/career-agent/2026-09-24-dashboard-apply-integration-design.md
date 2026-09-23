# Dashboard ↔ career_agent apply integration — design

## Problem

`career_agent` only runs from the CLI today (`python3 -m career_agent.apply --job-id N`).
The dashboard's `ApplyPanel` already says "Start the browser agent to fill the
application in your Chrome" but that copy is a lie — clicking "Mark as applied"
just writes a status row. This spec wires the dashboard to actually launch the
agent, and to show what it did, for jobs on an external ATS.

## Scope

- Trigger: one click on the Feed, for jobs the agent can actually handle.
- Live status while it runs: is it running, what page is it on, screenshot.
- Run history: what happened on the last run — which pages, login vs
  register, where it stopped and why, with a screenshot at that point.

Out of scope (explicitly deferred, not needed for the above):
- WebSocket / push updates — polling is sufficient (see "Live channel" below).
- A persisted roadblock/event table with live resolution UI in the dashboard
  — Telegram already is the HITL channel; this spec makes past runs
  *inspectable*, it doesn't replace Telegram as the *resolution* channel.
- Auto-submit from the dashboard — out of scope entirely; this integration
  never passes `--submit`. No durable-authorization mechanism for that exists
  in the codebase today (checked `career_agent/config/settings.py`); adding
  one is a separate, deliberate change gated by the project's own hard rule
  ("submit is gated by default... auto-submits only under a durable, revocable
  user authorization").
- Knowing the total page count of a form ahead of time — ATS forms are
  dynamic; the agent only learns "no more Next button" when it gets there.
  History shows "reached page N, stopped: X", never "N of 5".

## Trigger scope

The dashboard already computes `apply_type` per job
(`job_dashboard/match/apply_type.py`): `fill` is `"easy"` for `kind ==
"external-ats"` (real ATS host: greenhouse/lever/workday/ashby/icims/...) and
for `kind == "company-site"` (himalayas/remoteok/remotive link-outs, which
redirect to the company's own site). The new button is shown exactly when
`job.apply_type?.fill === "easy"` — no new classification needed.

## Architecture

```
Feed row (apply_type.fill === "easy")
        │ click "Apply with agent"
        ▼
patchStatus(id, "saved")     [existing endpoint — puts it on the Tracker board]
switch tab → Tracker          [existing UI state]
POST /api/jobs/{id}/apply-agent
        │
        ▼
subprocess: python3 -m career_agent.apply --job-id {id} --url {job_url}
(PYTHONPATH=src; never --submit)
        │
        ├─ real career-agent Chrome (CDP) fills the form live
        │  — dashboard's status endpoint opens its own READ-ONLY
        │    connect_over_cdp client to the same debug port to read
        │    page.url / page.title() / page.screenshot() on each poll
        │
        └─ LangGraph run, checkpointed to data/jobs_graph.db (SqliteSaver)
           — read after the fact by run_history.summarize_run()
```

## Component 1 — launch + live status (polling, not WebSocket)

**Live channel: polling.** The reference pattern this was compared against
(a Next.js dashboard with a `/ws` push channel) doesn't fit here: `career_agent`
runs as a **separate subprocess**, not in-process with the FastAPI server, so
pushing events would need new IPC between them. Polling reuses a pattern
already in this codebase (`RefreshButton.jsx` polls `GET /api/refresh/status`
every 1s) and needs no new server infrastructure. Given the agent's real-time
HITL channel is already Telegram (not the dashboard), sub-second push buys
nothing here.

**Backend** — new `src/job_dashboard/api/agent_routes.py` (own router, mirrors
`apply_routes.py`), included in `app.py`:

- `AgentRunState` — single-flight lock (same shape as `RefreshState` in
  `refresh_job.py`): one agent run at a time, since there's one shared
  career-agent Chrome profile.
- `POST /api/jobs/{job_id}/apply-agent`
  - Looks up `job_url` via `job_detail()`. 404 if the job doesn't exist.
  - 409 if a run is already active (any job).
  - `subprocess.Popen(["python3", "-m", "career_agent.apply", "--job-id",
    str(job_id), "--url", job_url], cwd=repo_root, env={**os.environ,
    "PYTHONPATH": "src"})`. stdout/stderr → `data/agent_runs/{job_id}.log`
    (kept as a debug tail; not the primary history source — see Component 2).
  - Stores `{job_id, pid, started_at}` in `AgentRunState`.
- `GET /api/apply-agent/status`
  - If a run is active: poll the subprocess (`Popen.poll()`); if still
    running, open a read-only `playwright.chromium.connect_over_cdp(cdp_url)`
    against the existing career-agent Chrome (same `CAREER_AGENT_CDP_URL` the
    agent itself uses), find the active page, and return
    `{running: true, job_id, url, title, screenshot}`, where `screenshot` is
    a path under `data/agent_runs/{job_id}/live.png` (overwritten each poll)
    — same convention as the history screenshots below, servable the same way.
    **This client only reads** (`page.url`, `page.title()`,
    `page.screenshot()`) — it must never call `.click()`/`.fill()`/navigate,
    since `career_agent` is the one actually driving that page and a second
    writer would race it.
  - If the subprocess has exited: flip state to `done` (exit code 0) or
    `error` (nonzero), clear the lock, return the terminal status once.
  - If no run has ever started: `{running: false, job_id: null}`.

**Frontend**:
- `api.js`: `launchApplyAgent(jobId)`, `fetchApplyAgentStatus()`.
- `Feed.jsx`: new button next to `+ Track`, rendered only when
  `j.apply_type?.fill === "easy"`; `stopPropagation` like the existing Track
  button.
- `App.jsx`: `onApplyAgent(id)` → `patchStatus(saved)` → `setActiveTab("tracker")`
  → `reloadAll()` → `launchApplyAgent(id)`; launch failures (404/409) surface
  in the existing top-level error banner.
- New `AgentStatusBadge.jsx` (copy of `RefreshButton`'s `setTimeout`-poll
  pattern) shown on the Tracker tab while `running`: status pill
  (`launching`/`running`/`done`/`error`) + "currently on: `<title>`" + a small
  screenshot thumbnail. Stops polling on `done`/`error`.

## Component 2 — run history (read, after the fact)

`apply.py`'s `_run_graph()` currently uses `langgraph.checkpoint.memory.InMemorySaver()`
— checkpoint state is lost when the subprocess exits, despite `graph.py`'s own
docstring and `career_agent/CLAUDE.md`'s data-paths table both already
claiming checkpoints persist to `data/jobs_graph.db`. Fix: swap in
`SqliteSaver` pointed at that path. LangGraph then keeps every node's state
(`classify → cred_provide → reach → perceive → fill → human_gate → advance`)
durably, keyed by `thread_id = sha1(job_url.encode()).hexdigest()[:16]`
(already computed in `apply.py:352`).

`AgentState` (`orchestrator/graph.py`) already carries almost everything
needed:

| Field | Meaning |
|---|---|
| `state["steps"]` | pages walked (incremented once per `fill_node` call) |
| `state["kind"]` | `classify_entry` result for the current page (`form`, `password`, `email_auth`, `closed`, ...) |
| `state["stopped_reason"]` | why the run ended: `stuck`, `max_steps`, `gate:<captcha>`, `auth_wall`, `reached_submit_dry_run`, `submit_declined`, `no_advance_control`, `security_email`, or `None` if it submitted |
| `state["pending_human"]` | the exact fields it was escalating when it stopped |
| `state["submitted"]` | whether it reached and clicked Submit (only possible with `--submit`, which this integration never passes) |

One new field: `state["cred_action"]` — `cred_provide_node` calls
`credential_provider.provide()`, which internally classifies the page via
`_classify_page_state()` (`"password"` vs `"registration"` vs `"otp"` etc.)
but currently discards that classification after acting on it. Thread it back
up as `cred_action: "login" | "register" | None` so run history can say which
one happened.

**Screenshots**: `_page_survey()` (`orchestrator/step_engine.py`, shared by
both the LangGraph path and the legacy `walk()` path) already takes a
full-page screenshot before every perceive step — but writes to a fixed path,
`/tmp/career_agent_{label}_survey.png`, which collides and overwrites across
runs and across jobs (label is just `perceive{steps}`, and `steps` resets to
0 every run). Change its signature to accept a `run_dir` and write to
`data/agent_runs/{job_id}/step{N}.png`, passed down from `apply.py` (which
already knows `job_id`).

**New**: `career_agent/orchestrator/run_history.py::summarize_run(thread_id,
db_path="data/jobs_graph.db")` — the only place that reads LangGraph's
checkpoint format. Walks `compiled_graph.get_state_history(config)` for that
thread (oldest → newest) and returns:

```python
[
  {"step": 1, "kind": "password", "cred_action": "register", "stopped_reason": None, "pending_human": [], "screenshot": "data/agent_runs/42/step0.png"},
  {"step": 1, "kind": "form", "cred_action": None, "stopped_reason": None, "pending_human": [], "screenshot": "data/agent_runs/42/step1.png"},
  {"step": 2, "kind": "form", "cred_action": None, "stopped_reason": None, "pending_human": [], "screenshot": "data/agent_runs/42/step2.png"},
  {"step": 3, "kind": "form", "cred_action": None, "stopped_reason": "stuck", "pending_human": [{"ref": "...", "label": "Why do you want to work here?"}], "screenshot": "data/agent_runs/42/step3.png"},
]
```

Dashboard-facing endpoint: `GET /api/jobs/{job_id}/agent-runs/latest` —
resolves `thread_id` from the job's `job_url`, calls `summarize_run`, rewrites
screenshot paths to servable URLs (mounted the same way résumé PDFs already
are), returns the list (404 if no run has ever happened for this job).

**Frontend**: `JobDetail.jsx` gets a new "Last agent run" section — an
ordered list of steps, each showing the page kind (application form / login
wall / registration) and fill progress; the step where `stopped_reason` is
set is visually distinct (e.g. amber) and shows the reason in plain language
plus its screenshot enlarged. A clean finish (last step has no
`stopped_reason`, or `stopped_reason == "reached_submit_dry_run"`) is shown as
success/"ready for you to review and submit" rather than a failure.

## Data flow summary

```
click → tracker (status write, existing)          [independent of the agent]
      → subprocess launch (dry-run always)          [Component 1]
      → poll: subprocess state + live CDP read       [Component 1]
      → subprocess exits
      → GET .../agent-runs/latest reads SqliteSaver-persisted
        checkpoint history via run_history.summarize_run()  [Component 2]
```

The two components are independent reads of independent sources (live poll
reads the *running* Chrome tab; history reads the *finished* checkpoint DB) —
neither blocks or depends on the other, so either can be built and tested on
its own.

## Error handling

- Launch: job not found → 404. Another run already active → 409 (frontend:
  "agent busy with another application"). `job_url` missing/blank → 422.
- Live status poll: if the CDP read fails (Chrome not up, tab closed) while
  the subprocess is still alive, return `{running: true, job_id, url: null,
  title: null, screenshot: null}` rather than erroring the whole poll —
  the subprocess state is still authoritative for "running".
- History: no checkpoint found for this job's `thread_id` (never run, or ran
  before this feature shipped and only has in-memory history) → 404 with a
  clear message, not a 500.
- A `patchStatus(saved)` that succeeds but a subsequent launch that fails
  never leaves inconsistent dashboard state — the job simply sits on the
  Tracker board un-applied, same as if the user had clicked the old "+Track"
  button alone.

## Testing

- Backend: `pytest` for `agent_routes.py` with `subprocess.Popen` stubbed —
  covers launch / 409 / status poll transitions (running → done, running →
  error) without touching a real Chrome or agent.
- Backend: `pytest` for `run_history.summarize_run()` against a small
  SqliteSaver checkpoint DB built by literally running the existing
  `build_graph()` with a stub page/deps through a few node transitions in a
  test — asserts the returned step list matches expected `kind`/`stopped_reason`
  ordering.
- Frontend: vitest asserting the "Apply with agent" button only renders for
  `fill === "easy"`, and that a click fires `patchStatus` → tab switch → the
  launch POST, in that order.
- Frontend: vitest for the "Last agent run" section rendering a stopped-mid-way
  fixture (3 steps, 3rd has `stopped_reason: "stuck"`) and a clean-finish
  fixture.

## Explicitly skipped (ponytail: cut corners, upgrade path)

- No new DB tables — history rides on LangGraph's existing (now-persisted)
  checkpointer instead of a bespoke `job_events`/`roadblocks` schema. Upgrade
  path: if `run_history.summarize_run()` ever proves too slow or the
  checkpoint format too awkward to query, replace it with real instrumentation
  writing to a dedicated table — the dashboard-facing endpoint's shape
  (`GET /api/jobs/{id}/agent-runs/latest`) doesn't have to change.
- No WebSocket — polling only. Upgrade path: if step-by-step live fill
  progress inside the dashboard (not just "running"/screenshot snapshots)
  becomes something you actually want to watch, that's when a push channel
  earns its complexity.
- No total-page-count estimate. Upgrade path: once enough successful runs
  exist per ATS vendor, a median step-count-to-submit per vendor (from
  `docs/career-agent/ats-graph.json`) could give a "usually ~5 pages"
  estimate — not attempted here.
