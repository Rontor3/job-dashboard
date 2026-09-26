# CDP Job Fetching: Indeed Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Checkbox steps.

**Goal:** Replace the jobspy Indeed scrape with a browser (CDP) Indeed adapter (India + Remote), title-gated, 30-day window, behind an off-by-default switch; then remove jobspy from Refresh.

**Architecture:** Same shape as `naukri.py`. Everything is read **passively from the documents the page itself loads**: the search page HTML (`in.indeed.com/jobs?...`) embeds `window.mosaic.providerData["mosaic-provider-jobcards"]` JSON (15 cards); a job page (`/viewjob?jk=<key>`) embeds a JSON-LD `JobPosting` with the full description. No API replay, no clicks. Spec context: `docs/career-agent/2026-09-25-job-source-research.md` (Indeed section said "blocked by Cloudflare Turnstile" on 2026-09-25; on 2026-09-27 the same CDP session loaded search + job pages with **no challenge** — this adapter must still treat any challenge as a hard stop).

**Tech Stack:** Python 3, `CdpSession` (`goto`, `capture`), pytest, existing runner/state/settings.

## Global Constraints

- Tests never touch a browser/network; the live smoke is gated by `RUN_CDP_TESTS=1`.
- Off by default: `browser_indeed_enabled = "0"` (default in `qa_store.DEFAULT_SETTINGS`); 48h min interval; never retried after a block.
- A Cloudflare/Turnstile challenge (document title "Just a moment…", `challenge-platform`/`cf-turnstile` in the body, or no mosaic JSON on a page that returned 200 **and** contains those markers) raises `Blocked` — never solve, never retry. A 200 page with neither marker and no mosaic JSON is treated as "no results" (not blocked).
- Only documents are read (`Capture.texts`), no `fetch`; no clicks; never touch Apply, saved jobs, or the candidate's Indeed account features.
- Order is `sort=date`; **skip `sponsored` cards** (ads). Cutoff on `pubDate` (epoch ms): jobs older than the window (incremental `ctx.hours`, exact; backfill 720 h) are dropped; a term/location walk stops after 2 consecutive pages with no card inside the window.
- **Title gate before any detail load:** only cards whose title passes `job_dashboard.match.relevance.is_target_role` are queued (the user complained about off-target Indeed jobs).
- Limits: incremental (max_pages 2, cap 40 loads), backfill (max_pages 3, cap 80). Terms: `machine learning engineer`, `ai engineer`, `data scientist`, `llm engineer`, `mlops engineer`. Locations: `India`, `Remote` (both on `in.indeed.com`).
- Detail budget: run **all search pages first, then spend the rest of the load budget on detail loads round-robin** (same as Naukri/LinkedIn).
- Stage only files you touched (concurrent uncommitted edits exist); no `Co-Authored-By` trailer; files < 500 lines.

## Verified shapes (live 2026-09-27)

- Search URL: `https://in.indeed.com/jobs?q=<term+plus>&l=<India|Remote>&sort=date&start=<0,10,20..>`. The HTML contains `window.mosaic.providerData["mosaic-provider-jobcards"]={...};` (regex: `window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*\n`, DOTALL). JSON path: `metaData.mosaicProviderJobCardsModel.results[]` with keys `jobkey, title, company, formattedLocation, pubDate (ms), formattedRelativeTime, sponsored (bool), snippet, indeedApplyable (bool), link`.
- Job page `https://in.indeed.com/viewjob?jk=<key>`: HTML with `<script type="application/ld+json">` whose JSON `@type == "JobPosting"` has `title, description (HTML, ~7k chars), datePosted, directApply, hiringOrganization.name, jobLocation`.
- Apply: `indeedApplyable` true (card) or `directApply` true (LD) ⇒ `native` (Indeed's in-site apply); otherwise `external` with no URL exposed (`apply_url=None`).

## Tasks (TDD, one commit each)

### Task 1: `Capture.texts()` + settings flag
- `session.py`: `Capture.texts()` yields `(url, status, text)` for each captured response whose `text()` succeeds (skip on exception). Fakes: add `FakeResponse(url, body, status)` `.text()` returning `body` if it is a `str` (else `json.dumps(body)`); tests in `tests/test_cdp_session_fetch.py` or a new `tests/test_cdp_session_texts.py`.
- `qa_store.DEFAULT_SETTINGS["browser_indeed_enabled"] = "0"`; `qa_routes.py` add `"indeed"` to the site loop (settings API) — check the existing loop over `("linkedin","naukri","wellfound","instahyre","iimjobs")`; test in `tests/test_cdp_settings_api.py` that the flag defaults False and toggles.

### Task 2: `indeed.py` parsing
Functions (with tests in `tests/test_cdp_indeed.py`, synthetic fixtures mirroring the shapes above):
- `SITE = "indeed"`, `TERMS`, `LOCATIONS = ("India", "Remote")`.
- `search_url(term, location, page) -> str` (`start = 10 * page`, `sort=date`).
- `parse_search(html) -> list[card]` where card = `{id: jobkey, title, company, location: formattedLocation, pub_ms, sponsored, native: bool(indeedApplyable)}`; cards missing `jobkey/title/company` dropped; malformed/missing mosaic JSON → `[]`.
- `parse_detail(html) -> {"description": html_to_text(...), "posted": date|None, "direct": bool} | None` from the JobPosting JSON-LD.
- `is_challenge(html) -> bool` (markers above).
- `to_listing(card, detail)`: `source="indeed"`, `external_id=jobkey`, `job_url="https://in.indeed.com/viewjob?jk=<id>"`, `posted_date` from `pub_ms` (fallback `datePosted`), `apply_kind="native" if card["native"] or detail["direct"] else "external"`, `apply_url=None`.

### Task 3: `run(session, ctx)`
Behaviour + tests (fake page script: `{url: [(doc_url, html_string)]}` — `FakePage` script items are `(response_url, body)`; a `str` body is a document):
1. Phase 1: for term in `ctx.terms`, for location in `LOCATIONS`, walk pages `0..ctx.max_pages-1`: `session.capture("in.indeed.com/jobs")` around `goto(search_url)`; any captured doc with `is_challenge` → `raise Blocked("challenge")`; cards from `parse_search`. Stats: `pages` += 1 per page that returned cards. Stop the walk after 2 consecutive pages with no non-sponsored card inside the window (`pub_ms/1000 >= now - hours*3600`).
2. Per fresh non-sponsored card: skip ids seen this run; skip titles failing `is_target_role` (`ctx.stats["off_target"] += 1`); `ctx.known(id, url)` → `skipped_known += 1`; else queue.
3. Phase 2: round-robin details: `goto(job_url)` capturing `in.indeed.com/viewjob`; `is_challenge` → Blocked; `parse_detail` gives description → listing; none → skipped (not known, retried next run).
4. `CapReached` → `ctx.stats["capped"] = True`, return what was collected.
Tests: fresh vs stale window stop rule; sponsored skipped; off-target title never gets a detail load; known skipped; challenge page raises `Blocked`; cap partial; missing description skipped and not counted known; two locations both searched; ids deduped across terms.

### Task 4: Register + remove jobspy Indeed
- `runner.py`: `ADAPTERS["indeed"] = (indeed.run, indeed.TERMS)`; `LIMITS_BY_SITE["indeed"] = {"incremental": (2, 40, 10**9), "backfill": (3, 80, 10**9)}`; add `"indeed"` to `EXACT_WINDOW`; `WINDOWS["indeed"] = (24, 48, 168, 720)`. Test like the other registration tests (off by default; must not open a session — pass a raising `session_factory`).
- `source_registry.py`: `REGION_SEARCHES = []` with a comment (jobspy retired: LinkedIn and Indeed are browser sources); adjust `tests/test_source_registry_terms.py::test_jobspy_results_are_title_gated` so it no longer assumes a jobspy fetcher exists first (assert the Himalayas fetcher is title-gated instead, patching `fetch_himalayas_jobs`).

### Task 5: Gated live smoke (lead runs it)
`tests/test_cdp_live_indeed.py` in the style of `tests/test_cdp_live_sites.py`: one term, one location, `max_pages=1`, 6 loads; assert non-empty listings with title/company/description, every title passes `is_target_role`, and print counts.

## After: gates
Enable with `PUT /api/agent-settings {"browser_indeed_enabled": true}` after the smoke passes; watch the first Refresh for `blocked:` notes.

## Self-review
Covers: passive documents only (T1-3), title gate before detail (T3), sponsored skipped, 30-day window on `pubDate`, challenge = hard stop, off by default, jobspy removed only after the adapter exists (T4), India + Remote locations. Deferred: Indeed apply URL (not exposed), reposts (Indeed refreshes `pubDate`; redate not implemented — skip-known only).
