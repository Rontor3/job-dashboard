# Dashboard UI — Design

## Purpose

The browsable surface over everything the backend already produces: aggregated jobs
(SQLite), embedding + LLM match scores, suspected duplicates, and — new in this
subsystem — job status tracking and a one-click pipeline refresh. Subsystem 2 of the
master design (see `2026-07-12-job-dashboard-design.md` §2); first UI-bearing sprint,
so it also establishes the project's visual system.

Decisions fixed here (user-confirmed 2026-07-13): **React + Vite SPA** frontend,
**FastAPI** JSON API, **minimalist/calm** visual register (`minimalist-ui` taste skill
drives tokens; impeccable audits the built UI), **background-job refresh with polling**.

## Architecture

Two processes in dev, one in daily use:

```
src/job_dashboard/
  api/
    __init__.py
    app.py            # FastAPI app factory; mounts /api/* + serves frontend/dist
    refresh_job.py    # background pipeline runner (daemon thread + status singleton)
  sources.py          # source registry: the six configured real fetchers for run_pipeline
frontend/             # Vite + React (all npm tooling isolated here; dist/ gitignored)
  src/
    App.jsx           # layout shell: header, filter bar, feed, detail panel
    api.js            # fetch wrapper for /api/*
    components/       # JobCard, JobDetail, FilterBar, ScoreBadge,
                      # DuplicatesSection, RefreshButton, StatusControl
    styles/tokens.css # design tokens (spacing, type scale, muted palette, one accent)
    styles/…          # per-component CSS
```

- Dev: `uvicorn job_dashboard.api.app:app` on :8000 + `vite dev` on :5173 with `/api`
  proxied.
- Daily use: `vite build` once; FastAPI serves the static `dist/` — one command, one
  port, no node at runtime.
- `db.py` remains the only module touching SQL. The API layer calls new query
  functions added to `db.py`.
- No auth; server binds 127.0.0.1 (localhost personal tool).

## API surface (JSON)

| Endpoint | Behavior |
|---|---|
| `GET /api/jobs` | Canonical jobs (duplicate_of IS NULL) joined with match_scores. Params: `q` (text search on title/company), `remote`, `location`, `job_type`, `source`, `status`, `min_score`, `sort` (`embed`/`llm`/`date`), `limit`/`offset`. Returns `{jobs: [...], total: n}`. Default feed excludes `dismissed` unless `status=dismissed` (or `include_dismissed=true`) is passed. `min_score` filters only when explicitly set — scores sort, they never hide by default. |
| `GET /api/jobs/{id}` | Full detail: description, embed_score, llm_score, verdict, strengths/gaps/flags (parsed from JSON columns), job_url, posted_date, and cross-listings (rows whose `duplicate_of` = this id → "also posted on: …"). 404 if unknown. |
| `PATCH /api/jobs/{id}/status` | Body `{"status": "saved" \| "applied" \| "dismissed" \| null}`; null clears to new. 422 on invalid value, 404 unknown id. |
| `GET /api/duplicates` | The suspected-duplicates listing (db.suspected_duplicates), each annotated with canonical id + source. Read-only in v1 — deletion remains an explicit future user command per the matching-engine spec. |
| `POST /api/refresh` | Starts the pipeline in a background thread; `{"started": true}`, or **409** if already running. |
| `GET /api/refresh/status` | `{running, stage, detail, last_result}`; stage ∈ `idle/ingesting/deduping/scoring/done/error`. |
| `GET /api/stats` | Header counts: total canonical, per-status counts, unranked count, last refresh summary. |

## Storage additions

- `jobs.status TEXT` (nullable; NULL = "new") — added with the same idempotent
  `PRAGMA table_info` + `ALTER TABLE` pattern as `duplicate_of`.
- New `db.py` functions: `set_job_status(conn, job_id, status)` (validates against
  {saved, applied, dismissed, None}; ValueError otherwise), `query_jobs(conn, …filters…)
  -> (rows, total)`, `job_detail(conn, job_id)`, `cross_listings(conn, job_id)`,
  `dashboard_stats(conn)`.
- Dismissed jobs stay in the database — the default filter merely excludes them, and a
  visible "show dismissed" toggle brings them back. Nothing is hidden irrecoverably.

## Source registry (`sources.py`)

The glue the matching-engine final review flagged as missing: a module exposing
`job_sources() -> list[callable]` and `company_sources() -> list[callable]` wiring the
six real fetchers (jobspy with the profile's search queries, remotive, remoteok, wwr,
himalayas, startup sheet) as no-arg callables for `run_pipeline`. Query terms/locations
come from the profile's search-queries file where applicable; kept in one place so
adding a source later is a one-line change.

## Refresh job (`refresh_job.py`)

- Module-level status object guarded by a lock; daemon thread runs
  `run_pipeline(conn, job_sources(), company_sources())` with its own SQLite
  connection (SQLite: one connection per thread).
- Stages reported: ingesting → deduping → scoring → done (or error). To report real
  stages without duplicating orchestration, `run_pipeline` gains an optional
  `on_stage(stage: str)` callback (default `None`, existing callers unaffected) that
  it invokes at each stage boundary; `refresh_job` passes one that updates the status
  object. `detail` carries the stage's summary counts once known (e.g. "scored 34 jobs").
- `embed_skipped` in the result (e.g. sentence-transformers missing, empty profile) is
  surfaced as a **non-fatal warning banner** in the UI — ingest/dedup results still
  land, per the matching-engine spec's isolation guarantee.
- Second `POST /api/refresh` while running → 409; the UI disables the button and polls.

## Frontend

Single-screen layout, minimalist register (dense rows over cards; data does the
talking; one accent color for scores):

- **Header**: title, `GET /api/stats` counts, RefreshButton (spinner + stage text while
  polling; warning banner when `embed_skipped`).
- **FilterBar**: search box, chips (remote, job_type, source, status), min-score
  slider (off by default), sort selector, "show dismissed" toggle.
- **Feed**: dense rows — title, company, location, source badge, posted date,
  ScoreBadge (embed % always; verdict pill once LLM-ranked). Click → detail panel.
- **JobDetail** (right-side panel): full JD rendered, scores, strengths/gaps lists,
  flags (deal-breakers/deadline/expired), StatusControl buttons, "apply ↗" link,
  "also posted on" cross-listings.
- **DuplicatesSection**: collapsed at the bottom ("Suspected duplicates (N)");
  expanding lists each with "suspected duplicate of #id — source". No delete action.
- Design tokens in `styles/tokens.css`, set by the `minimalist-ui` taste skill at
  implementation time; impeccable audits/polishes the built UI afterward.

## Error handling

- API: 404 unknown job, 422 invalid status, 409 refresh-in-progress; JSON error bodies.
- Frontend: inline error/empty states for every fetch (never a blank screen); refresh
  errors land in the status endpoint's `error` stage + banner.
- Pipeline failures never corrupt the feed: ingest/dedup/scoring isolation is already
  guaranteed by `run_pipeline`.

## Testing

- **Backend**: pytest via FastAPI `TestClient` against tmp SQLite dbs — endpoint
  contracts, filter combinations (incl. dismissed-exclusion default and min_score
  opt-in), status validation, refresh 409 + status transitions (with an injected fake
  pipeline), stats. No network, no real embedding model.
- **Frontend**: Vitest + React Testing Library — feed rendering from fixture JSON,
  filter state → query-param mapping, status buttons calling the API, refresh
  polling states. No browser E2E in v1; impeccable's live-browser pass covers
  visual/UX verification.
- Existing 49-test suite keeps passing; `pytest` stays scoped via `testpaths`.

## Non-goals (deferred)

- Application-tracking beyond the status field (`/outcome` archives, interview stages) —
  later sprint per master design §Application tracking.
- Cover letters, resume generation, outreach — later subsystems.
- Multi-user, auth, hosting beyond localhost.
- Deleting suspected duplicates from the UI — stays an explicit user command later.
- Mobile layout (desktop-first; responsive enough not to break, not optimized).
