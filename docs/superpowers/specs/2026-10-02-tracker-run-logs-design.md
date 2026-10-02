# Tracker + run logs — design

Date: 2026-10-02 · Status: approved in brainstorming, building

Slice 2 of the final functional flow (after `2026-09-27-jobs-page-queue-design.md`).

## Decisions

| question | decision |
|---|---|
| parked job (needs answers / login / review) | status **Failed**, with the reason shown on the row |
| run logs | Q→A table (already in `application_qa`) **+ one screenshot per page**, also for board runs |
| after answering a failed job's questions | **auto re-queue** once no open questions remain |
| top of the tracker | **only a pie chart** of statuses |

## Status model

Statuses (stored in `jobs.status`; internal names kept so nothing else breaks):

| shown | stored | set by |
|---|---|---|
| Queued | `saved` | + Queue / Apply |
| Applied | `applied` | runner, when the board confirmed the submission |
| Failed — *reason* | `failed` (new) | runner, for parked and failed runs; reason from `apply_queue.reason` |
| Interview round *N* | `interviewing` + `jobs.interview_round` (new, default 1) | tracker select now; email scan (slice 4) later |
| Selected | `offer` | tracker select / email scan |
| Rejected | `rejected` | tracker select / email scan |

`outcome()` now returns `failed` as the application status for parked runs too. `tracker_jobs`
returns a `failed` bucket and, per job, the queue `state`/`reason` and `interview_round`.
`dashboard_stats` gains `failed`.

## Auto re-queue

`POST /api/jobs/{id}/questions/{row}/reply`: after recording the answer, if the job has no open
questions left and its queue row is parked/failed, `queue.enqueue(job)` (back of the queue). The
runner picks it up when running; the bank now recalls the answer.

## Board run log + screenshots

`apply.py` passes `run_dir = data/agent_runs/<job_id>` to the board pipeline as it already does
for the graph. `boards.run.run_board` saves `perceive<N>.png` before reading each page and
`board_run.json` = `[{step, kind, stopped_reason, pending_human, screenshot}]` at stop — the same
shape `run_history.summarize_run` returns. `GET /api/jobs/{id}/agent-runs/latest` uses
`board_run.json` when the job is on a board (else the graph checkpoints, unchanged).
`AgentRunHistory` renders both unchanged, plus board stop reasons.

## Tracker UI

- `StatusPie` (replaces `Overview` on the tracker): donut of Queued / Applied / Failed /
  Interviewing / Selected / Rejected, legend with counts, total in the centre.
- Rows grouped In progress (queued, filling) → Failed → Applied → Interviewing → Selected,
  Rejected archived. Failed rows show their reason; Interviewing shows "Round N".
- Stage select: Queued, Applied, Failed, Round 1…5, Selected, Rejected.
- Expanded job: JD (collapsible), open questions (answer + save-as, existing `QuestionsPanel`),
  answers used with their source (existing `AnswersUsed`), last run with per-page screenshots
  (existing `AgentRunHistory`).

## Out of scope

Email status scan (slice 4) — it will set `interviewing`/round/`offer`/`rejected` through the
same `set_job_status`.
