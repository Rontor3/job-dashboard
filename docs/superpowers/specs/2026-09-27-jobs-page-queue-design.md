# Jobs page + apply queue — design

Date: 2026-09-27 · Status: approved in brainstorming, building

Slice 1 of the "final functional flow" (the others: tracker + run logs; answering — bank
onboarding, safety, prompts; Telegram escalation + email status scan).

## Problem

The board pipeline (`career_agent/boards/`) now applies on Naukri, LinkedIn, Indeed, iimjobs,
Instahyre, Wellfound and Work at a Startup, but the dashboard cannot use it:

- `match/apply_type.classify_apply_type` still hard-codes Naukri/LinkedIn as `manual`, so the
  Feed shows "Apply with agent" only for company ATS forms.
- One job at a time, by hand: `POST /api/jobs/{id}/apply-agent` starts one subprocess, then
  nothing follows it.
- A run blocks on the human (Telegram/CLI) for every unknown question, so an unattended
  sequence of applications stalls on the first gap.
- Submit needs `--submit --autonomous`, which the dashboard never passes.

## Decisions (from brainstorming)

| question | decision |
|---|---|
| queue order | FIFO in the order jobs are added; reorder/remove before or during a run |
| blocker (question the ladder can't answer, login wall, captcha, cap) | **park** the job, move to the next |
| submit | auto-submit only when that board's standing authorization is on **and** every answer is confident (existing `qbank_likely` rule); otherwise park |
| layout | left sidebar: title, nav (vertical tabs), filters, queue panel; job rows fill the rest |
| Instahyre related jobs | captured after a confirmed apply, scored, appended to the queue above the score threshold |

## Architecture

```
Feed row [route pill] [score] [Apply] [+ Queue]          Sidebar: nav · filters · QueuePanel
          │ Apply = enqueue(front) + start                     │ Start / Pause / reorder
          ▼                                                    ▼
   queue_routes ──► apply/queue.py (apply_queue table) ◄── apply/queue_runner.py (thread)
                                                            │ one job at a time, via AgentRunState
                                                            ▼
                        python -m career_agent.apply --job-id N --url U --park --result-json F
                                     [--submit --autonomous]  if autosubmit:<board> on
                                     [--review]               otherwise
                                                            │
                                     result file ──► outcome() ──► queue state + applications.status
```

There is one launch path: the Apply button enqueues the job at the front and starts the runner.
`POST /api/jobs/{id}/apply-agent` is kept for the CLI/extension and becomes a thin wrapper.

### Queue store — `src/job_dashboard/apply/queue.py`

Table `apply_queue(job_id PK, position REAL, state, reason, added_at, started_at, finished_at)`.
`state ∈ queued | running | parked | done | failed`. Functions: `ensure(conn)`, `enqueue(conn,
job_id, front=False)`, `remove`, `move(conn, job_id, before_job_id|None)`, `list_queue`,
`next_queued`, `mark(conn, job_id, state, reason=None)`. Re-enqueueing a parked/failed/done job
resets it to `queued` at the tail (or front). Position is a float so a move is one update.

### Outcome — `src/job_dashboard/apply/outcome.py`

Pure `outcome(result: dict|None, exit_code: int) -> (state, reason, app_status|None)`:

| run result | queue state | reason | applications.status |
|---|---|---|---|
| `submitted` true | done | `submitted` | `applied` |
| `stopped_reason` `ready_for_review` | parked | `review` (tab left open) | — |
| `apply_is_one_click` | parked | `one_click_needs_autosubmit` | — |
| `logged_out`, `challenge`, `daily_cap`, `captcha*` | parked | same | — |
| any `pending_human` | parked | `needs_answers` | — |
| no result file / exit ≠ 0 | failed | `crashed` / last reason | `failed` |
| anything else not submitted | parked | `stopped_reason` | — |

### Runner — `src/job_dashboard/apply/queue_runner.py`

`QueueRunner(db_path, launch, clock)`: `start()`, `pause()` (finish current job, take no next),
`status()`. A daemon thread loops: `next_queued` → `mark running` → build argv → `launch` (wraps
the existing `AgentRunState.start` + wait) → read result JSON → `outcome` → `mark` + set
application status → next. Stops when the queue has no `queued` rows or on pause. `launch` is
injected so tests use a fake. Only one runner per process; the single-flight lock stays
`AgentRunState`.

### Agent side — `src/career_agent/apply.py`

- `--park`: `HumanLoop` gets `ParkCollector` (records needs, sends one non-blocking Telegram
  note "N question(s) parked for <title> at <company> — answer on the tracker", returns `{}`)
  and `AutoDenyApprover`. Gaps stay open; the run ends with `pending_human` filled.
- `--result-json PATH`: the final result dict (`stopped_reason`, `submitted`, `pending_human`
  labels, `url`, `board`) is written there on every exit path, including errors.

Questions a parked run could not answer are already in `application_qa` (status needs-human) —
the tracker slice renders them editable; re-queueing the job then recalls them from the bank.

### Standing authorization

`agent_settings` keys `autosubmit_<board>` (`0`/`1`, default `0`; board ids without the
`board:` prefix, plus `career_site`). Read by the runner per job via `boards.profiles.board_for`
on the job URL. Toggled in the sidebar queue panel. Revoking takes effect from the next job.

### Route pill — `match/apply_type.py`

`classify_apply_type` consults `board_for(job_url)` first: a board URL → `{kind: <board id>,
label: "<Board>", fill: "agent"}`; LinkedIn with `apply_kind == "external"` → company site. The
"manual" band remains only for URLs no pipeline recognizes. Apply and + Queue render for every
job whose `fill != "manual"`.

### Instahyre related jobs

After `confirm` on `board:instahyre`, the driver captures the related-jobs list from the board's
response and returns it as `result["related_jobs"]`. The runner inserts them as jobs (source
`instahyre`), scores them with the existing matcher, and enqueues those ≥ the Feed's score
threshold. The response shape is unknown — the task starts with a live trace.

### Frontend

- `App.jsx`: CSS grid `240px 1fr`; `<Sidebar>` = title + stats, vertical `TabButton`s,
  `FilterBar` (Browse tab only), `QueuePanel`. Under 900px the sidebar stacks on top.
- `Feed.jsx` row right side: route pill, `ScoreBadge`, **Apply**, **+ Queue** (→ "✓ #n" when
  queued). "+ Track" is removed; queued/applied jobs reach the tracker through their status.
- `QueuePanel.jsx`: ordered list (↑/↓/✕), Start/Pause, the running job with a live link, parked
  count, per-board auto-submit toggles. Polls `GET /api/queue` every 3 s while running.

### API — `src/job_dashboard/api/queue_routes.py`

`GET /api/queue` → `{items:[{job_id,title,company,state,reason,position}], running, paused}`;
`POST /api/queue {job_id, front?}`; `DELETE /api/queue/{job_id}`;
`POST /api/queue/{job_id}/move {before?}`; `POST /api/queue/start`; `POST /api/queue/pause`;
`GET/PUT /api/queue/autosubmit {board: bool}`.

## Out of scope (later slices)

Tracker statuses/pie/expanded logs, JD-first Telegram escalation, promo/PII skip policy, the
shared "sounds like me" prompt, email status scan.

## Testing

Store, outcome and runner are pure/SQLite and unit-tested with a fake launcher. `--park` and
`--result-json` are tested through `_run_board` with fake page/human. Frontend: vitest for
QueuePanel and the Feed row actions; existing `feed`/`smoke` tests updated.
