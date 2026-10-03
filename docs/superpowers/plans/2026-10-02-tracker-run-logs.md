# Tracker + Run Logs Implementation Plan

Spec: `docs/superpowers/specs/2026-10-02-tracker-run-logs-design.md`.
Tests: `PYTHONPATH=src python3 -m pytest tests`; `cd frontend && npx vitest run`. Files < 500 lines.

### Task 1: Status model — `db.py`, `apply/outcome.py`, `apply/queue_runner.py`

- [ ] `failed` in `VALID_STATUSES`; `jobs.interview_round` column; `set_job_status(conn, id, status, round=None)`
- [ ] `tracker_jobs`: `failed` bucket; rows carry `interview_round`, `queue_state`, `queue_reason`
- [ ] `dashboard_stats["failed"]`; `outcome()` parked → `failed`
- Tests: `tests/test_tracker_status.py`, update `tests/test_apply_outcome.py`, `tests/test_queue_runner.py`

### Task 2: Auto re-queue — `api/qa_routes.py`

- [ ] reply: no open questions left + queue row parked/failed → `queue.enqueue`
- Test: `tests/test_requeue_on_answer.py`

### Task 3: Board run log + screenshots — `boards/run.py`, `apply.py`, `api/agent_routes.py`

- [ ] `run_board` saves `perceive<N>.png` per page and `board_run.json` at stop (ctx `run_dir`)
- [ ] `_run_board` gets `run_dir`; `/agent-runs/latest` reads `board_run.json` for board jobs
- Tests: `tests/career_agent/test_board_run_log.py`, extend `tests/test_agent_api.py`

### Task 4: Tracker UI — `StatusPie.jsx`, `TrackerBoard.jsx`, `App.jsx`, `api.js`

- [ ] donut + legend replaces `Overview` on the tracker
- [ ] groups, failed reasons, Round N, stage select with rounds, JD in the expansion
- Tests: `status_pie.test.jsx`, update `tracker_board.test.jsx`, `overview.test.jsx`
