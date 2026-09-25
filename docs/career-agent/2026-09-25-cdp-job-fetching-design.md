# CDP job fetching — design (LinkedIn, Naukri, Wellfound, Instahyre, IIMJobs)

Evidence and per-site measurements: `2026-09-25-job-source-research.md` (this spec does not repeat them).
Extraction sketches from that research: `job-source-research/*_fetch_sketch.py` (unreviewed, reference only).

## Goal

Read jobs from the candidate's already logged-in career-agent Chrome (`localhost:9222`, Playwright
`connect_over_cdp`) as part of the normal **Refresh**, with:

- **full descriptions** (a JobListing requires one),
- a **backfill** mode for the first fetch and an **incremental** mode afterwards,
- **no re-iteration of known jobs**: the stable key is checked before any detail fetch,
- the **native/external apply signal and the employer URL** where a site exposes them,
- a **smaller search-term set** without losing coverage,
- strict guardrails, since these are the candidate's real accounts.

## Decisions (and defaults chosen where none was given)

| Decision | Choice | Status |
|---|---|---|
| Trigger | part of the normal Refresh, gated by a per-site minimum interval (48h) | user chose |
| First adapter | **LinkedIn** | recommended, awaiting explicit confirmation |
| Add `apply_url` + `apply_kind` to JobListing | **yes** | user gave no preference: default = recommended |
| Indeed | **stays on jobspy; no CDP adapter** (blocked by Cloudflare on first navigation) | user gave no preference: default = recommended |
| Login | never automated. A site whose session has expired is skipped with an error | rule |
| Auto-apply | out of scope | rule |

Out of scope: hiring-signal extraction (separate spec), Indeed via CDP, any write action on a site.

## Architecture

New package `src/job_dashboard/sources/cdp/`:

```
session.py    CdpSession — the only place that touches Playwright
state.py      fetch_state table access + cadence gate
runner.py     fetch_browser_sources(conn, settings) -> (listings, [SiteResult])
linkedin.py   naukri.py   wellfound.py   instahyre.py   iimjobs.py    one adapter per site
```

**Adapter interface** (a function per site, no base class):
`fetch(session, ctx) -> Iterator[JobListing]`, where `ctx` carries `mode` (`backfill` | `incremental`),
`known(key) -> bool`, `terms`, `caps`, `anchor` (the site's saved cursor) and a `note(str)` callback for the
result line. Adapters are pure with respect to storage: they never read or write the database themselves.

**CdpSession** enforces the safety rules structurally instead of by convention:
- connects with `connect_over_cdp`, opens **its own tab**, and on exit closes only that tab and detaches
  (`browser.close()` detaches; verified not to close Chrome or other tabs);
- exposes only `goto`, `capture_responses(url_pattern)`, `scroll`, `wait`, and `page_fetch(url, headers)`
  (same-origin fetch from inside the tab). **It exposes no click, type or form API**, so an adapter cannot
  apply, save, follow or message;
- `nap()` = random 3-7s (LinkedIn 6-12s) before every navigation or replayed call;
- counts page loads and replayed calls against per-site caps and raises `CapReached`;
- classifies a page or response as blocked and raises `Blocked(reason)`: login redirect, captcha /
  Turnstile / "unusual activity", HTTP 401/403/429, Naukri 406. Adapters never catch `Blocked`;
- never persists request headers or tokens. Captured auth headers (Naukri bearer, Wellfound signature)
  live in memory for one run only.

**Runner** (`fetch_browser_sources`), per enabled site, in a fixed order:
1. skip with a note if Chrome is unreachable (`_cdp_reachable`, as in `agent_routes`); never launches Chrome;
2. cadence gate from `fetch_state` (skip if `now - last_run_at < min_interval` unless forced);
3. choose mode: `backfill` until `backfill_done`, else `incremental`;
4. run the adapter inside a `CdpSession`; collect listings; a `Blocked` or any exception ends **that site
   only**, is stored as `last_error`, and never aborts other sites;
5. update `fetch_state` (last run, counts, anchor, `backfill_done`).

**Pipeline integration.** `run_pipeline(..., browser_fetch=None)` gains a stage `"browser sources"` before
ingest; the returned listings go through the existing `insert_job` -> `mark_duplicates` -> classify -> embed
path unchanged. The result dict gains `"browser": [SiteResult]`. `refresh_job._summarize` prints one line per
site. The frontend's Refresh status shows the stage name and per-site lines.

## Data model

`JobListing` gains `apply_url: Optional[str]` and `apply_kind: Optional[str]` (`native` | `external` |
`unknown`). `jobs` gains the same two columns via `ALTER TABLE ... ADD COLUMN` (guarded, idempotent) plus
`CREATE INDEX jobs_source_ext ON jobs(source, external_id)`. Existing rows stay NULL.

`classify_apply_type` (dashboard) consults `apply_kind` / `apply_url` first and falls back to its current
URL heuristic when NULL: an `external` job whose `apply_url` is on a known ATS host is `easy`; `native` is
`manual`. The Apply-with-agent button and the agent's `--url` use `apply_url` when present.

`fetch_state(site TEXT PRIMARY KEY, last_run_at, last_success_at, backfill_done INTEGER, last_new INTEGER,
last_skipped INTEGER, last_error TEXT, anchor TEXT)` — `anchor` is site-specific JSON (e.g. newest
`liveStartAt` seen, max Instahyre id).

Settings (`agent_settings`, editable later): `browser_min_interval_hours` (48), and per site
`browser_<site>_enabled` (default on for LinkedIn only until each adapter passes its live gate).

**Key rule.** `external_id` is the site's stable id and `source` is `linkedin` / `naukri` / `wellfound` /
`instahyre` / `iimjobs`; `known(key)` is `EXISTS (source, external_id)`. `job_url` stays the canonical
`UNIQUE` URL (tracking params stripped) as a second guard. Naukri additionally dedupes on normalized
title+company+location; `mark_duplicates` still catches cross-site reposts after ingest.

## Modes

| | Backfill (first run, until the feed is exhausted) | Incremental |
|---|---|---|
| Depth | large caps, slower pacing | small caps |
| Time window | widest verified filter | narrowest filter covering the interval |
| Resume | **implicit**: known jobs are skipped, so a capped run continues from where new jobs begin next time | n/a |
| Ends | `backfill_done` set only when the feed is exhausted (empty page / window end) | after `stop_after_known` consecutive known jobs (only where the order is newest-first) or the window end |

Correctness depends only on skip-known. Time filters and stop-early are optimisations; **stop-early is used
only where ordering was verified newest-first** (LinkedIn `sortBy=DD` roughly, Wellfound `LAST_POSTED`, not
Instahyre).

## Per-site adapters

Caps are per run. "Detail" = the extra fetch needed for a full description of a **new** job only.

### LinkedIn — first adapter
- **List:** `/jobs/search/?keywords=<term>&location=India&sortBy=DD&f_TPR=<window>&start=<0,50,...>`;
  capture `voyagerJobsDashJobCards` responses (50 cards/page) and the graphql prefetch.
- **Window:** backfill `r2592000`(month), incremental `r604800` (verified). `r172800` (48h) is a
  **verify-before-build gate**; until verified, incremental uses `r604800` and relies on skip-known.
- **Key:** `external_id = <numeric id>`, canonical URL `https://www.linkedin.com/jobs/view/<id>`.
- **Description:** first ~24 cards carry it in the prefetch; others via `/jobs/view/<id>` (detail).
- **Apply:** `EASY_APPLY_TEXT` => `native`; else `external` with `companyApplyUrl` (prefetch) or the
  `linkedin.com/safety/go/?url=` href on the job page => `apply_url`.
- **Terms:** `machine learning engineer`, `ai engineer`, `data scientist`, `llm engineer`, `mlops engineer`,
  `senior data scientist`, `risk data scientist` (7 terms, 95.7% of relevant in testing), 2 pages each.
- **Caps:** backfill 60 page loads, incremental 30. Pacing 6-12s. Hard stop on any checkpoint / authwall.

### Naukri
- **List:** in-page `jobapi/v3/search` (20/page) using the headers the page itself sent. **Prefer a
  UI-triggered call** (click page 2 / sort) over a replay; replaying tripped `406 recaptcha` after ~16 calls.
  Whether the UI-triggered variant avoids it is a **verify-before-build gate**. Any 406 = `Blocked`.
- **Window:** backfill `jobAge=30`, incremental `jobAge=3` (day granularity; `createdDate` in ms).
- **Key:** `jobId` (12 digits, first six = DDMMYY); canonical `https://www.naukri.com` + `jdURL`.
- **Description:** detail page JSON-LD (1 load per new job). The list snippet is only ~0.9k characters.
- **Apply:** `applyRedirectUrl` present => `external` + `apply_url`; else `native`.
- **Terms:** few broad terms (`machine learning engineer`, `data scientist`, `ai engineer`, `llm engineer`)
  x deep pages, **untested for coverage** (a follow-up experiment under `jobAge=1|3` decides).
- **Caps:** <=12 API/UI calls per run (below the ~16 that tripped the check) + detail loads for new jobs.

### Wellfound
- **List:** in-page replay of the persisted graphql query `JobSearchResultsX`
  (`filterConfigurationInput{page, sortBy:LAST_POSTED, hideOffPlatformJobs:false, ...}`), using the page's own
  `x-apollo-signature` / `x-wf-cfp` / `x-apollo-operation-name` captured at runtime. ~22 jobs/page.
  **Fail closed on any 4xx** (the operation id and signature can rotate on deploys). One walk; **no terms**.
- **Window:** client-side cutoff on `liveStartAt`: backfill 30 days, incremental `anchor` (newest seen) minus
  1 day; stop after 2 consecutive empty pages.
- **Key:** numeric `id`; canonical `https://wellfound.com/jobs/<id>-<slug>`; key on `id` only.
- **Description:** in the list payload; **never open detail pages** (they emit a `PREVIEW`/`TrackView`
  interaction on the real account).
- **Apply:** `autoPosted:true` => `external` (`apply_url` unavailable); otherwise `native`.
- **Caps:** page loads 1-2; replayed calls <=25 backfill / <=8 incremental.

### Instahyre
- **List:** same-origin `GET /api/v1/job_search?skills=<term>&offset=N&company_size=0&job_type=0&isLandingPage=true`
  (20/page), via `page_fetch`. Order is relevance, so **no stop-early**.
- **Window:** none server-side. Client rule `job_id >= anchor` (job ids rise with date, 34/34 samples: an
  **unguaranteed assumption**, always combined with skip-known).
- **Key:** `job_id` from the URL/JSON `id`; never the per-candidate opportunity id.
- **Description:** `GET /job-<id>-x/` JSON-LD (1 request per new job).
- **Apply:** all `native`; no external URL exposed.
- **Terms:** `machine learning engineer`, `data scientist`, `ai engineer`, `llm engineer`, `mlops engineer`,
  `applied scientist`; backfill 10-15 pages each (relevance decays after ~offset 400), incremental 2-3 pages.
- **Caps:** backfill 90 requests, incremental 30.

### IIMJobs
- **List:** `GET gladiator.iimjobs.com/job/search?query=<term>&page=N&posting=<days>` (50/page), `page_fetch`.
- **Window:** backfill `posting=30`, incremental `posting=3`; `createdTimeMs` is precise.
- **Key:** numeric `id` (also the trailing `-<id>` of the URL); reposts get a new id (accepted).
- **Description:** `GET /job/detail?jobcode=<id>` -> `introText` (1 call per new job).
- **Apply:** `applyStatus=1` => `native`; `2` with `applyUrl` => `external` + `apply_url`.
- **Terms:** `data scientist`, `ai engineer`, `machine learning engineer`, `llm engineer` (3 covered 100% of a
  7-day window); expect ~22-25 real roles/week, so the adapter ships **disabled by default** (low value).
- **Caps:** 40 requests.

### Indeed
No adapter. jobspy continues to supply it.

## Search terms

Core set replacing the 24 in `source_registry.SEARCH_TERMS` **for browser sources only** (jobspy keeps its
own list until re-measured): `machine learning engineer`, `ai engineer`, `data scientist`, `llm engineer`,
`mlops engineer`, `applied scientist`, `senior data scientist`, `generative ai engineer`,
`risk data scientist`, `fraud data scientist`. Each adapter uses the subset above. Dropped for adding almost
nothing anywhere: `forward deployed engineer`, `nlp engineer`, `deep learning engineer`, `data scientist iii`,
`staff data scientist`.

## Guardrails (summary)

Own tab only; no click/type API; pacing 3-12s; per-site page/call caps; **stop on any block**, never retry
a block; no login, no captcha solving; Chrome never launched or restarted by the fetcher; auth headers
memory-only; per-site enable switch; 48h minimum interval with a force flag on the refresh API (no new
button yet); one run at a time (Refresh is already single-flight).

## Error handling and reporting

Per-site `SiteResult {site, mode, new, skipped_known, pages, note}`; `note` values:
`skipped: Chrome not reachable`, `skipped: next fetch in 31h`, `session expired`, `blocked: recaptcha`,
`cap reached (resumes next run)`, `done`. A blocked site never affects the others or the API sources, and
its `last_error` is shown on the next Refresh.

## Testing

- **Adapters against recorded fixtures** (trimmed JSON per site, no PII, no tokens): mapping to
  JobListing, key extraction, apply-kind/`apply_url`, time-window parsing.
- **CdpSession with a fake page:** cap enforcement, `Blocked` classification for each signal, own-tab-only
  cleanup, no headers persisted.
- **Runner:** cadence gate, mode selection, backfill resume ("second run over the same feed opens zero
  detail pages"), stop-early only where enabled, a blocked site isolated from the rest.
- **Schema:** idempotent column migration; `classify_apply_type` precedence of `apply_kind` over the heuristic.
- **Live smoke** (manual, gated by `RUN_CDP_TESTS=1`): one small real fetch per site.

## Phasing and live gates

Each adapter needs its live gate passed **before** it is enabled by default.

1. **Framework + LinkedIn + schema (`apply_url`, `fetch_state`) + pipeline integration.** Gate: verify
   `r172800` (or keep `r604800`), and one supervised real run.
2. **Naukri.** Gate: UI-triggered search avoids the 406; term-coverage experiment under `jobAge`.
3. **Wellfound.** Gate: re-capture headers on a fresh session; confirm `LAST_POSTED` cutoff on a second day.
4. **Instahyre.** Gate: confirm `id >= anchor` still holds after a few days.
5. **IIMJobs** (disabled by default).

## Known ceilings and risks

- Replaying a site's own signed/authenticated calls (Naukri, Wellfound) carries ToS and fragility risk;
  the signature/operation scheme can change without notice (fail closed, re-capture).
- LinkedIn's time filter follows the refreshed listing time, so reposts look new; skip-known by id removes
  most of the cost, and reposts keep their id.
- Naukri and Instahyre term reduction is unproven under result caps.
- Instahyre's `id >= anchor` recency and reposts-keep-id on Wellfound/Instahyre are unverified.
- Accounts can still be flagged despite the caps; the caps are deliberately small.
