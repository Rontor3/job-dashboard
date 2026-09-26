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
  (same-origin fetch from inside the tab). **It exposes no general click, type or form API**, so an adapter
  cannot apply, save, follow or message. The one exception is `click_pagination(selector)`: it works only for a selector the adapter has declared in
  an allowlist, and at runtime refuses unless the element sits inside a pagination landmark (`nav`,
  `[role=navigation]`, `aria-label*=pagination`) and its label is a page number / "next"; it refuses anything
  whose text or href matches apply / interested / save / follow / message / send / share. (A tab-control
  variant was designed for Naukri's recommended feeds; it is not built until those are un-deferred.) Adapters prefer `goto` / API offsets and use this only when a site has no other way;
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

## Retention rule (decided 2026-09-26)

Jobs older than **30 days** are deleted, and the fetcher never asks for more than 30 days back, so a deleted job
cannot be re-imported and no "seen keys" list is needed. Every backfill window is therefore capped at 30 days:
LinkedIn `f_TPR=r2592000`, Naukri `jobAge=30`, IIMJobs `posting=30`, Wellfound a 30-day `liveStartAt` cutoff,
Instahyre `id >= anchor` for the date 30 days back. Known residual: a job posted >30 days ago but *renewed*
(LinkedIn, Naukri) looks fresh and is re-imported; that is a live listing, so it is accepted.
The one-off prune on 2026-09-26 removed 13,123 of 22,220 rows (older than 30 days by posted date, falling back to
first fetched; no tracker status; no application/résumé/letter/question/run history), with their match scores,
and reset 1,612 duplicate markers. Backup: `data/backups/jobs_2026-09-26_pre-prune.db`. A recurring prune is not
built yet; it would apply the same rule.

## Modes

| | Backfill (first run, until the feed is exhausted) | Incremental |
|---|---|---|
| Depth | large caps, slower pacing | small caps |
| Time window | widest verified filter | narrowest filter covering the interval |
| Resume | **implicit**: known jobs are skipped, so a capped run continues from where new jobs begin next time | n/a |
| Ends | `backfill_done` set only when the feed is exhausted (empty page / window end) | after `stop_after_known` consecutive known jobs (only where the order is newest-first) or the window end |

Correctness depends only on skip-known. Time filters and stop-early are optimisations; **stop-early is used
only where round-2 replay showed it holds** (see the next section): Naukri date sort, Wellfound `LAST_POSTED`,
LinkedIn `sortBy=DD` (with a wider window as the safety net). Not Instahyre or IIMJobs.

## Round 2: day-2 dedupe, tested per platform

The plan is one fresh scrape, then a daily refresh that skips known jobs. Each site was tested on: key
stability (same query twice, >=10 min apart), a saved baseline (`data/research_baselines/<site>_2026-09-25.json`,
gitignored, for a **genuine day-2 comparison the next day**), and an offline replay (treat jobs older than a
cutoff as known, read in the site's real order, stop after N consecutive known, measure pages and recall).
Baselines: LinkedIn 450 rows (272 unique jobs), Wellfound 434, Instahyre 417, Naukri 160 rows (114 unique),
IIMJobs 50.

| Site | Key stable | Skip-known + stop-early | Daily cost (measured) | Verdict |
|---|---|---|---|---|
| **Wellfound** | yes (141/141) | **exact**: stop at the first page whose newest job is older than the cutoff (+ small margin); N=10 recalled 70/70 | ~7 pages + ~8 keyword queries, ~25 calls, hard cap 40 | **viable** |
| **Naukri** | yes (Jaccard 0.9, new jobs shift in at the top) | works at N=10 in a small sample (recall 1.00, timestamps spanned only 2.7h) | ~3 pages/term, 12-15 loads for 4 terms | **viable, first scrape is expensive** |
| **LinkedIn** | yes (Jaccard 1.0) | N=10 recalls ~92-95% (scaled cutoffs; order violated newest-first on 45-52% of adjacent pairs) | 2-3 pages/term, 6-9 loads for 3 terms | **partly**: the ~5-8% missed are caught next day because the window is wider than the cadence |
| **Instahyre** | yes (Jaccard 1.0) | **stop-early does not work** (recall 0/3: each term's pool is 7-9k jobs and new ones land at random ranks) | fixed ~15 pages x ~6 terms (~90 list calls) + 5-30 detail fetches | **partly**: skip-known works at the detail step only |
| **IIMJobs** | yes (Jaccard 1.0) | not needed: the whole `posting=3` window is 4 requests | 4 requests + ~15 detail calls | viable, **low value** (~27 real roles/week) |
| Indeed | n/a | n/a | n/a | not applicable (jobspy) |

Findings that change the per-site design:
- **Naukri.** The date sort is `?jobAge=1&sort=f` (works on cold URLs and `-N` page suffixes), newest-first with no
  pinned items. `createdDate` is the **last renew time**, not the first post time (18 of 60 jobs had an old jobId
  date but a fresh `createdDate`); skip-known by `jobId` treats renewed jobs as known, which is what we want.
  One term-day is ~2,700-3,300 results (~137 pages) except `llm engineer` (136); narrowing helps but does not
  fix it (`experience=3` 527; city slug 643; the role-category UI filter 477 has no reproducible URL param).
  Pages past 10 work. There is no title-only search. **Unresolved:** one agent reported the list payload
  carries the full description, contradicting two earlier passes (~1k-character snippet); keep the detail
  fetch until a real job's payload length is compared with its detail page.
- **LinkedIn.** `f_TPR=r172800` (48h) **works** (1,093 results vs 900 for 24h, 1,428 for 7d). Reposts are 33% of
  cards and keep the same id and listed time across loads. Descriptions arrive only for the first ~24 cards per
  page (216 of 450), so skip-known **does** save the detail loads for the rest. A 7-day window is ~900-1,900
  results per term, so the backfill is capped and partial, not exhaustive.
- **Wellfound (reverses the earlier "no terms needed").** The feed shows at most **3 jobs per startup**, and 95 of
  200 startups are at that cap; relevant jobs are hidden (a startup showing 3 has 7+; its "NLP Engineer" and
  "Data Scientist L1" appeared only when searched by title). The daily procedure is the unfiltered
  `LAST_POSTED` walk **plus ~8 keyword/title queries** (1-3 pages each, same stop rule). Reposts keep their id
  (liveStartAt refreshed on 1 of 102), so dedupe by id, never by time.
- **Instahyre.** UI numbered pages call the same API (`offset=20`, `offset=40`): identical ids and order, so
  no click is needed. Job id vs date: Pearson 0.9965, **0 violations in 3,081 pairs** over 79 dated jobs, ~205
  ids/day; a safe anchor is the first id of the cutoff date minus ~250 (`datePosted` is date-only, so the
  boundary is fuzzy by about a day). There is no server-side recency signal. `id >= anchor` avoided 390 of 400
  detail fetches in the replay. **Budget concern:** ~90 list calls a day is more than any other site; the
  adapter starts with fewer terms and pages (3-4 terms) and raises depth only if the measured new-job density
  justifies it.
- **IIMJobs.** Read the whole `posting=3` window every time; stop-early lost a job at N=5. `posting=1` works.
  0 reposts-under-new-id in the window. ~27% of relevance-filter passes are false positives.

Not verified anywhere: a real day 2 (the saved baselines allow it), reposts on a later day, and the true 48h
recall (the replays used cutoffs scaled down to the timestamps each site's sample spanned).

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
Read **passively**: the adapter navigates (or makes an allowlisted pagination click) and captures the responses the *page itself* issues. **It never replays an API call**:
replaying `jobapi/v3/search` from the tab is what triggered `406 recaptcha` after ~16 calls in the first pass;
the second pass made 23 loads, 3 tab clicks and 2 pagination clicks with no challenge.

- **Deferred (not in v1): the recommended-jobs page** (`/mnjuser/recommendedjobs`, four tabs Applies /
  Profile / Preferences / You might like, 183 distinct jobs, each tab one whole-list call
  `POST /jobapi/v2/search/recom-jobs`). Researched but parked: it needs a tab-click allowlist and an answer to
  whether the feeds include jobs the candidate already applied to on Naukri (the payload has no applied flag,
  so unchecked, they could be imported as fresh jobs and applied to twice). Only 11 relevant jobs overlap
  with search, so it is a real additional source when it is picked up.
- **v1 source: term search with paging.** Numbered pages are real: URL `/<term-dashes>-jobs`, `-jobs-2`,
  `-jobs-3`, ...; the bar shows pages 1-10 + Next; **20 jobs per page, no overlap between pages**. The
  earlier "no search call on plain load" was wrong: in 20 of 21 loads the page itself fired
  `GET /jobapi/v3/search?...&pageNo=N`, which the adapter captures passively (one cold load fired nothing:
  retry once by reloading, else skip the page). `?jobAge=3` combines with page N (machine-learning-engineer
  fell from 48,427 to 5,228 results); the oldest job on pages 1-2 was still 80h old, and results are ordered by
  relevance by default. The site's sort menu has a **Date** option (seen in the first pass as `sort=f`; a
  UI-paged click added `sort=p`, presumably relevance): **use the date sort**, so order is newest-first and
  stop-at-known / stop-at-cutoff are valid on Naukri. That fixes the *order*, not the *volume*: a broad term is
  large even per day (5,228 results in 3 days for "machine learning engineer", roughly 1,700/day, i.e. ~85
  pages/day/term against a ~60-load budget), and the first pass called the date sort noisy (test / .NET roles
  mixed in). So depth is still capped per term (backfill 5 pages, incremental 3) and `jobAge=1` is used where
  the cadence allows. **Verify-before-build gates:** (a) the exact sort parameter and that order is really
  monotonic by date; (b) the real per-day volume per term under `sort=f&jobAge=1`; (c) whether the search
  can be narrowed (title-only matching, experience or location filters) to make a day readable. UI paging (`click_pagination`) issues `pageNo=N` with
  `sort=p` and `sid` added and also returned 200; it is the fallback if a URL-load stops firing the call.
- **Coverage.** Search pages 1-3 of three terms gave 167 jobs (165 relevant). Term reduction for Naukri stays
  open (relevance ordering means even a windowed result set can't be fully read).
- **Payload.** The search response gives `jobId`, `title`, `companyName`, `createdDate` (ms), `jdURL`, `companyApplyJob`,
  `applyRedirectUrl` and a `jobDescription` HTML of ~1k characters. That is not the full description: new jobs
  still need the detail page (JSON-LD), one load each.
- **Key.** `jobId` (12 digits, first six DDMMYY), identical across tabs and search pages. Canonical URL =
  `https://www.naukri.com` + `jdURL`. Consultancies post many near-duplicates (one posted 26 ids in a day), so
  dedupe additionally on normalized title+company+location before the detail step.
- **Apply.** `companyApplyJob == true` always carries `applyRedirectUrl` (the employer's ATS link), in the list
  itself: `external` + `apply_url`; otherwise `native`. Observed 181 native / 93 external of 274 jobs.
- **Window / modes.** Backfill `jobAge=30`,
  incremental `jobAge=3` (day granularity; `createdDate` in ms for exactness).
- **Terms (search only):** `machine learning engineer`, `data scientist`, `ai engineer`, `llm engineer`.
- **Caps.** ~60 page loads per run (4 terms x up to 5 pages, plus detail loads for new jobs; fewer in
  incremental), 6-12s pacing, at most once or twice a day; stop at once on any 403/406/429/captcha.
- **Round-2 status:** gate (a) done (`sort=f`, newest-first); (b) measured (~2,700-3,300 results per term per
  day); (c) partly (filters exist, none title-only). Still to verify: the full-description claim, the
  near-duplicate collapse on real data, and a real day 2.

### Wellfound
- **List:** in-page replay of the persisted graphql query `JobSearchResultsX`
  (`filterConfigurationInput{page, sortBy:LAST_POSTED, hideOffPlatformJobs:false, ...}`), using the page's own
  `x-apollo-signature` / `x-wf-cfp` / `x-apollo-operation-name` captured at runtime. ~22 jobs/page.
  **Fail closed on any 4xx** (the operation id and signature can rotate on deploys). The daily run is the unfiltered walk **plus keyword/title queries** (see Round 2).
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
- **Pagination.** The site shows numbered pages at the bottom of the results, and page 2, 3, ... give
  different jobs (the research found page 2 shares none with page 1). The adapter reads them through the
  underlying `job_search` offset (`offset = 20 * (page - 1)`), which needs no click. **Gate:** confirm that
  UI page N returns the same jobs as offset `20*(N-1)`. If it does not (or the API stops working), fall back
  to `click_pagination` on the allowlisted page-number / "next" control, moving one page at a time with the
  normal pacing.
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
`risk data scientist`, `fraud data scientist`. Each adapter uses the subset above. On Naukri the term search with paging is the v1 source (the recommended feeds are deferred); on Wellfound the unfiltered walk is supplemented by ~8 keyword/title queries because of the 3-jobs-per-startup cap. Dropped for adding almost
nothing anywhere: `forward deployed engineer`, `nlp engineer`, `deep learning engineer`, `data scientist iii`,
`staff data scientist`.

## Guardrails (summary)

Own tab only; no general click/type API (only the allowlisted pagination click); pacing 3-12s; per-site page/call caps; **stop on any block**, never retry
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

1. **Framework + LinkedIn + schema (`apply_url`, `fetch_state`) + pipeline integration.** Gate: one supervised real
   run. (`r172800` is verified to work.)
2. **Naukri.** Gates: the passive search source works end to end on a supervised run with no 406; the
   near-duplicate collapse is checked on real data; term-coverage under `jobAge`.
3. **Wellfound.** Gates: re-capture headers on a fresh session; confirm the `LAST_POSTED` cutoff on a second day
   (baseline saved); measure how many hidden jobs the keyword queries recover.
4. **Instahyre.** Gates: `id >= anchor` still holds after a few days (page/offset equivalence is verified);
   new-job density per term to set depth.
5. **IIMJobs** (disabled by default).

## Known ceilings and risks

- Replaying a site's own signed/authenticated calls (Naukri, Wellfound) carries ToS and fragility risk;
  the signature/operation scheme can change without notice (fail closed, re-capture).
- LinkedIn's time filter follows the refreshed listing time, so reposts look new; skip-known by id removes
  most of the cost, and reposts keep their id.
- Naukri and Instahyre term reduction is unproven under result caps.
- Instahyre's `id >= anchor` recency and reposts-keep-id on Wellfound/Instahyre are unverified.
- Accounts can still be flagged despite the caps; the caps are deliberately small.
