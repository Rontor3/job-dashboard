# Matching Engine — Design

## Purpose

Score every aggregated job listing against Rakshit's profile so the Dashboard UI (next
subsystem) can sort and filter by fit. Scores are **aids, never gates**: all listings remain
visible; nothing is hidden by scoring. Cross-source duplicates (the same role posted on
multiple boards) are collapsed under one canonical row.

Decided during brainstorm (2026-07-13): build this **before** the Dashboard UI, so the
dashboard is designed around real scores rather than a reserved empty slot.

## Prerequisites (both done)

- **Job Aggregation** (Phase 1): deduplicated-by-`job_url` SQLite feed with full JD text.
- **Profile onboarding**: `01-candidate-profile.md` (skills/experience/projects, GitHub-enriched)
  and `04-job-evaluation.md` (personalized 5-dimension evaluation framework, remote-first
  location logic, verdict thresholds).

## Architecture

Two-stage hybrid scoring, appended to the existing ingest into one pipeline:

```
run_pipeline
  ├─ 1. ingest        → new jobs into SQLite (existing run_ingest, unchanged)
  ├─ 2. dedup         → mark cross-source duplicates (duplicate_of)
  ├─ 3. embed-score   → EVERY unscored canonical job: local sentence-transformers
  │                     cosine similarity vs composed profile text → embed_score (0-1)
  └─ 4. deep-rank     → top N unranked canonical jobs by embed_score (default 30,
                        configurable) get full LLM evaluation via parallel Claude
                        Code subagents scoring against 04-job-evaluation.md
```

- Stage 3 is free, local, and covers the whole feed — this is the score used for
  dashboard-wide filtering/sorting.
- Stage 4 is enrichment (strengths/gaps/verdict/flags) on the most promising slice; it
  never removes or hides jobs outside the slice.
- LLM runtime: **Claude Code subagents** (the ai-job-search `/rank` pattern) — uses the
  existing subscription; no API key or local model dependency.

## Profile text composition

`match/profile_text.py` composes the embedding query at runtime from:
- `01-candidate-profile.md`: Technical Skills + Professional Experience + Independent Projects
- `04-job-evaluation.md`: career goals / target titles

Kept deliberately **broad** (user directive: do not overfit the system to one narrow
profile — open across AI Engineer / ML Engineer / Senior DS / DS3 and related titles).
The composed text is SHA-256 **hashed** and the hash stored with every score, so a later
profile change makes stale scores detectable and re-scorable.

## Cross-source dedup

`match/dedup.py`, after ingest:
- Normalize `(company, title)` per job: lowercase, strip punctuation and filler noise.
- Group canonical-candidate rows by the normalized key; the **earliest-fetched** row in a
  group is canonical; the rest get `duplicate_of → jobs.id` (new nullable column).
- Duplicates are **marked, never deleted** (user directive 2026-07-13): suspected
  duplicates are surfaced under their own "Suspected duplicates" section in any
  listing/report output, each annotated with the canonical job it is believed to
  duplicate (e.g. "suspected duplicate of #42 — jobspy:linkedin"). The user verifies
  the logic against real data first; rows are removed only on an explicit later
  command, never automatically.
- Scoring (stages 3–4) runs only on canonical rows (`duplicate_of IS NULL`).

## Storage

New table plus one column, owned by `db.py` (which remains the only SQL in the codebase):

```sql
ALTER TABLE jobs ADD COLUMN duplicate_of INTEGER NULL;  -- → jobs.id of canonical row

CREATE TABLE match_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,      -- → jobs.id
    embed_score REAL NOT NULL,           -- stage 3, every canonical job
    profile_hash TEXT NOT NULL,          -- profile version that produced the score
    llm_score INTEGER,                   -- stage 4, top-N only (0-100 weighted)
    verdict TEXT,                        -- Strong/Good/Moderate/Weak/Poor Fit
    strengths TEXT,                      -- JSON list
    gaps TEXT,                           -- JSON list
    flags TEXT,                          -- JSON: deal-breakers, deadline, expired
    scored_at TEXT NOT NULL,
    llm_scored_at TEXT
);
```

Schema changes are applied idempotently by `init_db` (CREATE TABLE IF NOT EXISTS; the
ALTER guarded by a column-existence check) so existing databases upgrade in place.

## Components

| Unit | Purpose | Depends on |
|---|---|---|
| `match/profile_text.py` | Compose + hash broad profile text | profile markdown files |
| `match/embedder.py` | Embed profile + JD texts, cosine → embed_score | sentence-transformers |
| `match/dedup.py` | Mark cross-source duplicates | db |
| `db.py` (extended) | match_scores table, duplicate_of column, score upsert/read | sqlite3 |
| `pipeline.py` | `run_pipeline()` orchestrating ingest → dedup → embed → rank handoff | all above |
| `/rank` (Claude Code command) | Parallel subagents evaluate top slice per 04-job-evaluation.md, write results | pipeline output |

The evaluation rubric stays in `04-job-evaluation.md` (already personalized) — the code
never hard-codes scoring dimensions, so tuning the rubric needs no code change.

## Error handling

- **sentence-transformers missing:** pipeline still runs ingest + dedup; embed stage
  reports a clear install instruction and leaves jobs unscored (pending), never crashes.
- **LLM agent failure:** isolated per job — one failed evaluation doesn't abort the rank
  batch (same philosophy as ingest's per-source isolation).
- **Profile files missing/empty:** scoring refuses to run with an actionable error naming
  the missing file; ingest + dedup still proceed.
- **Re-scoring:** rows whose `profile_hash` differs from the current profile hash are
  treated as unscored (stale) and re-scored on the next run.

## Testing (no network; consistent with the existing suite)

- Fake embedding model returning deterministic vectors → embed_score computation and
  ordering testable without downloading a model.
- Dedup unit tests on synthetic cross-source rows (same role via LinkedIn + Indeed
  fixtures; near-miss titles that must NOT merge).
- `match_scores` upsert idempotency + profile-hash staleness tests.
- Pipeline end-to-end test wiring fake sources + fake embedder.
- LLM stage tested at its boundary: the function that validates and writes an agent's
  result JSON. Agents themselves are exercised live, not unit-tested.

## Non-goals (deferred)

- Dashboard UI (next subsystem — designed after this, around these scores).
- Embedding-similarity-based dedup (v1 uses normalized company+title; revisit if false
  negatives show up in practice).
- Score calibration from application outcomes (`/outcome` feedback loop — later plan).
- Scheduling/cron for the pipeline (decide once it runs manually end-to-end).
