# Observability family — candidate designs (O)

Author: orchestrator GLM (own analysis, complements the two nav designs and the
answer-pipeline brief). Evidence: `src/career_agent/boards/run_log.py`,
`src/career_agent/browser/page_shot.py`, `run_log` table, classifier report.

## Current state (facts)

| Instrument | What it does | Hole |
|---|---|---|
| `boards/run_log.py` | per-page `perceive<N>.png` after fill + final stop shot + `board_run.json` written once at `finish()` | a mid-run death (class F EPIPE) → **nothing**: 30604 has no `board_run.json`, no shots |
| `page_shot.capture_page` | full-page or 0.9-viewport slices, best-effort | parts feed is `.name_*.png`; no step provenance inside the artifact |
| `run_log` table | one row per finished run | crash rows end stopped_reason NULL (39 since Oct 1) — queue_runner re-queues only `state='running'` rows; a killed run whose queue row finished stays a NULL zombie |
| assist (claude_assist.py) | `recover()` on stop | dies silently on quota (`You've hit your weekly limit`) — wasted attempts, no fallback (30285.log:13-15) |
| screenshots from perception | tmp `career_agent_perception.png` verify-copy | overwritten every snapshot — no history; retry storm (`_2.._6`) is in the artifact but not keyed by step |

## Candidate O1 — step-paired crash-durable trace (recommended core)

One append-only JSONL per run: `data/agent_runs/<id>/trace.jsonl`, one line per
event `{t, step, kind: perceive|decide|fill|gate|ask|shot|stop, payload keys,
screenshot paths}`. `board_run.json` stays as the tracker's summary, now also
rebuildable FROM the trace. `Filled/finished` semantics unchanged; pages keep the
current filenames, but every shot with the screenshot meta sidecar gets the
store job_id/job_url/step written as a JSON sidecar `<name>.json` (PNG-safe,
filesystem-only). Filled-counting and minute-overview stays from existing lines.
Product: crash impossible to lose context, `_2..6` repeats easy to diff.

Cost: ~1 day (BoardRunLog already centralizes page shots + finish; route every
`log()` call through a `trace.event()` writer). Risk: none — additive.

## Candidate O2 — orphan & dead-ask reconciliation

Startup pass in queue_runner.drain (already does the `'running'→queued` fix):
1. `UPDATE run_log SET stopped_reason='crash_orphaned' WHERE ts>=now-24h AND (stopped_reason IS NULL OR stopped_reason='') AND job_id NOT IN (SELECT job_id FROM apply_queue WHERE state IN ('queued','running'))`
2. Telegram asks persist to a `telegram_replies` queue table at send-time
   (ask payload + run_key) so the reply survives the process and the next run
   of the SAME job consumes it (W: run swaps mid-reply → run_key binding guard).
3. `stalled_no_progress` watcher parks currently write NO run_log row —
   give the watcher a `record_park()` that always leaves a row (the classifier
   confirmed 0 rows ever for this reason).

Cost: ~1 day of Queues/DB; risk: stale-reply consumption guarded by run_key.

## Candidate O3 — child-process (Node) health

Class F: the Node bridge died with EPIPE while Python waited mid-ask.
- Supervisor: spawn with a detached shell/process group, listen for SIGCHLD/
  exit events; on death while mid-ask: (a) mark `assist_node_dead`, (b) restart
  the helper once, (c) if restart fails → **skip assist, continue with the
  deterministic path** instead of abandoning the whole job; the run's stop
  reason reflects the assist state, never swallows the fill progress.
- Wrap every write into a `try:` with EPIPE detection (errno -32) and
  re-spawn-with-backoff. Never let the child's lifetime outlive the ask.
- Always flush `trace.jsonl` + `board_run.json` in a `finally:` (today they
  die with the process — the 30604 hole).

Cost: ~2 days (careful with the CDP attach lifecycle); the payoff is a
never-abandon run.

## Candidate O4 — assist quota fallback ladder

Claude assist cap 5/site is fine but dies on weekly quota:
1. Detect the quota sentence in the reply (string match, 2 sites use it);
2. Ladder: quota → local LLM assist (Ollama is already a hard dependency per
   the 1cd4e61 commit) → deterministic data-driven heuristics only → park.
3. Never spend the run's retry budget on a dead channel (30285/30833 show
   exactly that wasted cycle; 5s timeout + recovery call could instead go
   straight to the entry-chain fallback of the nav fix).

Cost: ~0.5 day. Cross-fam: pairs naturally with nav designs' entry chains.

## Candidate O5 — screenshot corpus hygiene

- Sidecar `.json` (job_url, step, ts, shot kind) next to every shot (from O1);
- keep the tmp `career_agent_perception.png` verify-copy but ADD a rolling
  hash-named duplicate `perceive_step<N>` for the decision that consumed it
  (modest growth; enables before/after diffing when fills misfire);
- the run summary gains `screenshot_manifest` (already in board_run.json shape).

## Scoring (rubric 1–5)

| | reliability (kill the hole) | generality | blast radius↓ | effort↓ | testability |
|---|---|---|---|---|---|
| O1 trace+sidecars | 5 | 5 | 5 | 4 (1d) | 5 |
| O2 orphans/dead-asks | 4 | 4 | 4 | 4 (1d) | 4 |
| O3 child health | 5 | 4 | 3 (CDP lifecycle risk) | 2 (2d) | 3 |
| O4 assist ladder | 4 | 3 | 5 | 4 (0.5d) | 4 |
| O5 shot corpus | 3 | 3 | 5 | 4 (0.5d) | 4 |

**Order: O1 → O2 → O4 → O3 → O5** (each independent; O1 is the spine the
others report through; O3 justified when class F costs another lost run).
