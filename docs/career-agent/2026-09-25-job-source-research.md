# Job-source research: fetching from logged-in sites over CDP

Research run 2026-09-25 by six read-only agents (one per site) driving the career-agent Chrome
(`localhost:9222`, Playwright `connect_over_cdp`). Wellfound was run twice (logged out, then logged in).
Nothing was clicked, applied to, or logged into. The agents' verified extraction code is in
`job-source-research/` next to this file (unreviewed research sketches, not production code).

## 1. Summary

| | Logged in on :9222 | Fetch | Full description | Unique key | Time filter | Apply model |
|---|---|---|---|---|---|---|
| **LinkedIn** | yes | listen to the search page's own responses (50 cards/page) | first ~24 cards; then 1 load/job | `linkedin:<id>` | **yes, hour-level** (`f_TPR`) | 39% Easy Apply, **61% external**, employer URL readable |
| **Naukri** | yes | replay its `jobapi/v3/search` in-page (20/page) | 1 load/job (list has a ~0.9k snippet) | `naukri:<jobId>` + title/company/location dedupe | **yes, day-level** (`jobAge`), ms timestamp | 70% native, **30% external**, URL in `applyRedirectUrl` |
| **Wellfound** | yes (re-run) | persisted graphql `JobSearchResultsX` replayed in-page; or public role pages | **in the list** | `wellfound:<id>` | no filter; `sortBy=LAST_POSTED` + client cutoff on `liveStartAt` | 98% native; `autoPosted:true` = external; URL not exposed |
| **Instahyre** | yes | `GET /api/v1/job_search` (20/page) | 1 request/job | `instahyre:<job_id>` | none (job id rises with date) | 100% native ("express interest") |
| **IIMJobs** | yes | `gladiator.iimjobs.com/job/search` (50/page) | 1 call/job | `iimjobs:<id>` | **yes, day-level** (`posting`) | 95% native; external URL in `applyUrl` |
| **Indeed** | n/a | **blocked**: Cloudflare Turnstile on the first automated navigation | — | — | — | — |

**Why the apply model matters.** Only *external* jobs can go to the career agent, and only LinkedIn and Naukri
expose the employer URL without a click. The other sites are discovery sources. The current
`apply_type.py` heuristic cannot see any of this; the JobListing needs an `apply_url` + native/external field.

## 2. Per site

### LinkedIn (cleanest; highest ban risk)
- **Fetch.** Load `/jobs/search/?keywords=…&location=India&sortBy=DD&f_TPR=r86400[&start=50]` and capture the
  `voyagerJobsDashJobCards` responses the page already makes: 50 cards/load. A graphql prefetch adds full
  description and apply info for only the first ~24 cards; the rest need `/jobs/view/<id>`.
- **Key.** Numeric id from `/jobs/view/<id>`. Reposts keep the original id (62 of 188 jobs were reposts).
- **Time.** `f_TPR=r3600|r86400|r604800` verified: filtered results stayed in-window (max 23.9h for the 24h
  filter; unfiltered reached 480h). Card carries a millisecond timestamp. Catch: the filter follows the
  *refreshed* listing time, so a repost counts as new; a 24h window holds ~500-1100 results per term.
  `sortBy=DD` is only roughly ordered.
- **Apply.** 188 unique jobs: 73 Easy Apply, 115 external. The card's Easy Apply flag matched detail data on
  82/82. Employer URL readable without clicking (`companyApplyUrl` in the prefetch or the
  `linkedin.com/safety/go/?url=` href).
- **Risk.** No challenge in 25 page loads. Prior project notes flag ban risk: keep caps small.
- **Not verified:** the ~1000-result cap, boolean OR search, id stability across days, personalisation.

### Naukri
- **Fetch.** Search pages are server-rendered; the JSON API fires only on UI interaction. Replaying
  `/jobapi/v3/search` in-page with the page's own headers worked ~15 times, then **406 "recaptcha required"**.
  Treat 406 as a hard stop; a UI-triggered call (click page 2/sort) is an untested safer variant. Direct
  `/jobapi/v4/job/<id>` also 406'd. Full JD is in the JSON-LD of the detail page.
- **Key.** 12-digit `jobId`; the first six digits are the creation date (DDMMYY). Consultancies post
  near-duplicates under different ids: also dedupe on title+company+location.
- **Time.** `jobAge=1|3|7|15|30`, works but by calendar day (`jobAge=3` -> oldest 76h). `createdDate` is ms.
  `sort=f` (newest) is noisy; use default order + `jobAge`.
- **Apply.** Of 229 relevant jobs: 161 native (70%), 68 external (30%); `applyRedirectUrl` present for all 77
  external jobs seen, so no click needed. 80 native jobs carry screening questions.
- **Not verified:** how deep pagination goes, reposts, 9 of 24 terms (stopped at the 406), logged-out baseline.
- **Correction (from the user):** search results have numbered pages 2, 3, 4, ... The research fetched only
  page 1 per term, so "20 jobs per term" below is a page-1 figure, not a cap on the search.
- **Also (from the user):** the logged-in recommended-jobs page has four personalised feeds (applies, profile,
  preferences, you-might-like); not researched, see the fetch design.

### Naukri, second pass (feeds and pagination; no API replays)
23 page loads, 3 tab clicks, 2 pagination clicks; no 403/406/429/captcha. It corrects parts of the first pass.
- **Recommended page** = four tabs (Applies 40, Profile 53, Preferences 75, You might like 75), each filled
  by `POST /jobapi/v2/search/recom-jobs` (`clusterId` null/profile/preference/similar_jobs) returning the
  **whole list at once**: no paging. 183 distinct jobs; overlap between tabs is 20-29 except "You might like".
- **Search pages** `<term>-jobs-N` (bar shows 1-10), 20 jobs/page, no overlap between pages. **Correction:**
  the page itself fires `GET /jobapi/v3/search?...&pageNo=N` on load (20 of 21 loads), so it can be captured
  passively. `?jobAge=3` works with page N (48,427 -> 5,228), but results are relevance-ordered: the oldest
  job on pages 1-2 was 80h old.
- **Apply:** 181 native / 93 external of 274; `applyRedirectUrl` in the list payload for every external job.
- **Coverage:** search 167 jobs (165 relevant), feeds 183 (150 relevant), only 11 relevant in both.
- **Payload:** `jobDescription` HTML ~1k chars (not the full JD); the detail page still holds the full text.
- **Not verified:** whether applied jobs are hidden from the feeds; search depth beyond page 3.

### Wellfound (logged in)
- **Fetch.** `/jobs` is client-rendered; jobs come from `POST /graphql` persisted query
  `JobSearchResultsX` (variables `filterConfigurationInput{page, equity, remotePreference, salary,
  yearsExperience, sortBy, hideOffPlatformJobs, customJobTitles, keywords}`), 10 startups (~22 jobs)/page. It
  requires the page's own `x-apollo-signature`, `x-wf-cfp`, `x-apollo-operation-name`; capturing them from the
  page's request and replaying via in-page `fetch` worked for ~250 calls. Full description is in the payload.
  The operation id/signature can rotate on deploy: fail closed on any 4xx and re-capture.
- **Public alternative (no login).** `wellfound.com/role/l/<role>/india?page=N`: server-rendered
  `#__NEXT_DATA__`, 20 startups/page, full descriptions, same id space (117 shared ids, identical
  `liveStartAt`). Only 6 role slugs resolve (machine-learning-engineer, ai-engineer, data-scientist,
  data-science, artificial-intelligence-engineer, machine-learning-scientist).
- **Key.** Numeric `id` (`/jobs/{id}-{slug}`), stable across sessions (52/52). The slug can change.
- **Time.** No date filter (`postedWithinDays` rejected). `sortBy=LAST_POSTED` works; feed order is by the
  startup's newest job, so old jobs appear on every page. Walk newest-first, cut off client-side on
  `liveStartAt`, stop after 2 empty pages. Of 433 India jobs: 29 <=24h, 123 <=72h, 217 <=7d.
- **Apply.** `autoPosted:true` = external (6/6 confirmed by toggling `hideOffPlatformJobs`); only 2.1% of jobs
  (4 of 140 relevant). ATS-synced jobs (Greenhouse/Ashby/Lever/Workable) stay native. External URL is not in
  the payload or DOM (`offsiteListingUrl` only on click).
- **Search terms.** `customJobTitles` is a near-exact match; the 24 terms are almost disjoint and 9 return 0.
  One unfiltered `LAST_POSTED` walk filtered by `is_target_role` gave 31 relevant jobs in 7 days vs 32 from
  the public role pages: **terms are unnecessary on Wellfound.**
- **Side effect:** the agent opened one detail page (job 4735154), which sent `CreateInteraction PREVIEW` /
  `TrackView` on the real account. Avoid detail pages. Also ~250 replayed calls: more ToS risk than page loads.
- **Not verified:** `roleTagIds`, the external URL, repost id behaviour, the 3-jobs-per-startup cap, remote roles.

### Instahyre
- **Fetch.** `GET /api/v1/job_search?skills=<term>&offset=N&company_size=0&job_type=0&isLandingPage=true`,
  20/page, same-origin `fetch`. `candidate_matching` is a personalised feed with no keyword search. Full
  description only on `/job-<id>-x/` (JSON-LD), 1 request/job.
- **Key.** `instahyre:{job_id}` (URL / JSON `id`). The 10-digit opportunity id is per-candidate: don't use it.
- **Time.** None; default order is relevance. Job ids rise with date (34/34), so `id >= anchor` is a
  usable but unguaranteed recency rule. Detail gives a date only.
- **Apply.** 34/34 native ("Apply now" = express interest, no href); no external URL anywhere.
- **Coverage.** 24 terms -> 357 jobs, 301 relevant; each term matches ~10k jobs and page 2 shares 0 with page
  1: depth matters more than terms. Relevance drops after ~offset 400.

### IIMJobs (technically fine, low value)
- **Fetch.** `GET gladiator.iimjobs.com/job/search?query=<text>&page=N&posting=<days>` (50/page);
  `/job/detail?jobcode=<id>` -> `introText`. Overlap between pages: dedupe by id.
- **Key.** `iimjobs:<id>`; reposts get a new id. **Time.** `posting=3|7|15|30` verified, `createdTimeMs` precise.
- **Apply.** `applyStatus=1` native / `2` external with `applyUrl`. 526 native vs 27 external overall.
- **Yield.** ~37 relevant hits/week, ~10 false positives (e.g. "LLM" matches law degrees): ~22-25 real roles.
  Skews senior/recruiter postings.
- **Process note:** ~13 navigations plus ~100 API GETs (over the 90 budget if API calls count); one stray
  `/jobfeed` tab may remain open in your Chrome.

### Indeed (blocked)
The first search in a fresh CDP-driven tab returned a Cloudflare Turnstile challenge; the agent stopped, per
the rules. It looks like fingerprinting of the automated tab, not rate limiting. Indeed already flows through
jobspy (11,618 rows), so nothing is lost by skipping CDP for it.

## 3. Reducing the 24 search terms

Greedy set-cover over each site's raw results (recomputed independently of the agents):

| Site | Terms tested | Relevant union | 95% | 100% | Trustworthy? |
|---|---|---|---|---|---|
| LinkedIn | 12 | 70 | **7** | 10 | fair (page 2 added +41%: depth matters) |
| IIMJobs (7-day) | 24 | 37 | **3** | 3 | yes: the result set was exhaustible |
| Wellfound | 24 (title search) | 68 | 10 | 13 | moot: one walk needs no terms |
| Naukri | 15 | 229 | 13 | 15 | **no**: page 1 only (20/term) |
| Instahyre | 24 | 366 | 20 | 24 | **no**: page 1 (+ a few page 2) only |

**Caveat.** Naukri and Instahyre "need every term" only because only **page 1 (20 jobs)** of each search was
read out of thousands of matches (both sites have numbered pages 2, 3, ...), so every term looks unique. The data cannot prove that fewer terms lose nothing there; the honest
plan is few broad terms x deep pages x a time window small enough to exhaust. **Untested.**

Terms that added almost nothing anywhere: `forward deployed engineer`, `nlp engineer`, `deep learning engineer`,
`data scientist iii`, `staff data scientist`. Candidate core set (10, down from 24):
`machine learning engineer`, `ai engineer`, `data scientist`, `llm engineer`, `mlops engineer`,
`applied scientist`, `senior data scientist`, `generative ai engineer`, plus the domain-tilted
`risk data scientist` and `fraud data scientist` (unique on LinkedIn).

## 4. Fetch modes (proposal, from the above)

| Site | First fetch (backfill) | Every-other-day |
|---|---|---|
| LinkedIn | `f_TPR=r2592000`-style month window, 2 pages x ~7 terms, slow pacing | shortest verified window covering 48h (`r604800` verified; `r172800` unverified) + skip-known |
| Naukri | `jobAge=30`, few broad terms, deep pages | `jobAge=3` |
| Wellfound | `LAST_POSTED` walk to a 30-day cutoff | walk to `last_run - 1 day`, stop after 2 empty pages |
| Instahyre | ~6 terms x 10-15 pages | first pages + `id >= anchor`; **stop-early is invalid** (relevance order) |
| IIMJobs | `posting=30`, 3-4 terms | `posting=3` |

Skip-known (check the stable key before opening any detail page) is the layer everything depends on; the
time filter and stop-early rules are optimisations.

## 5. Risks and process notes
- **Bot detection is real.** Indeed on the first navigation; Naukri after ~16 replayed API calls; the rest
  clean at ~25-85 loads. Keep volume small, treat 4xx/406 as a hard stop.
- **Replaying a site's signed/authenticated calls** (Naukri, Wellfound) is more ToS-exposed than page loads;
  never persist the captured auth headers (the agents kept them in memory only).
- **Account side effects.** One Wellfound detail page recorded a preview event. Otherwise nothing was clicked.
- **Unreviewed research.** The automated reviewer timed out on the second Wellfound run; its outputs were
  checked manually (no stored tokens, cookies or saved-search data).

## 6. Open decisions
1. First adapter (LinkedIn recommended: verified, hour-level filter, 61% external with a readable URL;
   Wellfound is low-risk but 98% native).
2. Add `apply_url` + native/external to `JobListing` (recommended).
3. Indeed: stay on jobspy only (recommended) vs. try reading an already-open tab.
