# Jobs Page + Apply Queue Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Spec:
> `docs/superpowers/specs/2026-09-27-jobs-page-queue-design.md`.

**Goal:** Queue jobs from the Feed and apply to them one after another with the right agent,
parking any job that needs the human instead of blocking the queue.

**Architecture:** SQLite `apply_queue` + a daemon-thread runner in the API process that launches
the existing `career_agent.apply` subprocess per job (`--park --result-json`), maps the result
to queue state and application status, then takes the next job.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest; React + vitest.

## Global Constraints

- Files < 500 lines; new routes go in `api/queue_routes.py`, not `agent_routes.py`.
- Nothing is submitted unless `autosubmit_<board>` is `1`; the existing `qbank_likely` rule
  still blocks autonomous submit.
- A parked run never waits on the human.
- Tests: `PYTHONPATH=src python3 -m pytest tests`; `cd frontend && npx vitest run`.

---

### Task 1: Queue store — `src/job_dashboard/apply/queue.py`

**Test:** `tests/test_apply_queue.py`

- [ ] enqueue appends in add order; `front=True` goes first; re-enqueue of a done/parked job resets to queued
- [ ] `move` before another job / to the end; `remove`
- [ ] `next_queued` skips running/parked/done; `mark` stamps started/finished times
- [ ] `ensure` is called from `init_db`

### Task 2: Outcome mapping — `src/job_dashboard/apply/outcome.py`

**Test:** `tests/test_apply_outcome.py` — one case per row of the spec table.

### Task 3: Agent `--park` and `--result-json` — `src/career_agent/apply.py`, `integrations/park.py`

**Test:** `tests/career_agent/test_park_mode.py`

- [ ] `ParkCollector.__call__(fields)` returns `{}`, notifies once (injected `notify`), never raises
- [ ] `write_result(path, result)` writes JSON with `stopped_reason`, `submitted`, `pending_human` labels; called on every exit path (try/finally), including exceptions (`stopped_reason: "error"`)
- [ ] `--park` builds `HumanLoop(AutoDenyApprover(), collector=ParkCollector(...))`

### Task 4: Runner — `src/job_dashboard/apply/queue_runner.py`

**Test:** `tests/test_queue_runner.py` (fake `launch(job_id, argv) -> (exit_code, result)`)

- [ ] runs queued jobs in order, one at a time; stops when none are queued
- [ ] argv: `--park --result-json`; `--submit --autonomous` only if `autosubmit_<board>`=1, else `--review`
- [ ] maps outcome → `mark` + `set_application_status`/job status on `applied`/`failed`
- [ ] `pause()` finishes the current job and takes no next; `start()` while running is a no-op
- [ ] a launcher exception marks the job failed and the queue continues

### Task 5: Route pill from board profiles — `src/job_dashboard/match/apply_type.py`

**Test:** extend `tests/test_apply_type.py` — Naukri/iimjobs/Instahyre/Wellfound/YC/Indeed/LinkedIn board URLs → `fill: "agent"`; unknown host stays `manual`.

### Task 6: API — `src/job_dashboard/api/queue_routes.py` (+ include in `app.py`)

**Test:** `tests/test_queue_api.py` with a fake runner — list/add/remove/move/start/pause/autosubmit; `apply-agent` becomes enqueue-front + start.

### Task 7: Sidebar layout — `frontend/src/App.jsx`, `components/Sidebar.jsx`

**Test:** `smoke.test.jsx` — nav buttons in the sidebar switch tabs; FilterBar only on Browse.

### Task 8: Row actions + QueuePanel — `components/Feed.jsx`, `components/QueuePanel.jsx`, `api.js`

**Test:** `feed.test.jsx` (Apply → enqueue front + start; + Queue → "✓ #n"), `queue_panel.test.jsx` (order, ↑/↓/✕, start/pause, autosubmit toggles).

### Task 9: Instahyre related jobs

- [ ] live trace of the post-apply related-jobs response (human apply with network capture)
- [ ] driver returns `related_jobs`; runner inserts, scores, enqueues ≥ threshold
