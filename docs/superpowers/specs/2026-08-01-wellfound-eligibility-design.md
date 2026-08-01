# Wellfound Source + Eligibility Filter — Design

## Purpose

Two related additions so the dashboard shows **only jobs the candidate is
genuinely eligible for, at the top**:

1. **Eligibility filter** — a reusable check that runs for *every* source after
   normalization and, when a job fails a hard eligibility bar, **down-ranks it to
   "Weak"** (which the dashboard hides by default) rather than dropping it — so
   nothing vanishes but ineligible jobs sink out of view. This is what would have
   caught the "10+ years required, candidate has ~2" case.
2. **Wellfound source** — an on-demand, browser-session ingestion path (Wellfound
   has no public API and gates its GraphQL feed behind login + bot protection),
   normalizing Wellfound jobs into the same `JobListing` the other sources
   produce.

Decisions fixed (user-confirmed 2026-08-01):
- **Fail behavior = down-rank, not drop.** A failing job is kept + deep-ranked but
  its verdict is capped at **"Weak"**, with a human-readable flag.
- **Rules = (a) experience gap and (b) region acceptance** only. Visa/location/
  work-mode are already handled by the existing visa-aware deep-rank rules and are
  NOT duplicated here.
- **Scope = all sources** (LinkedIn / Naukri / Wellfound alike).
- **Gap strength = strong** — a large experience gap reliably sinks the job to
  "Weak".

## Component 1 — `match/eligibility.py`

Pure, side-effect-free logic (no DB/network), unit-tested.

- `EligibilityResult(demote: bool, flags: list[str])` — `demote=True` means the
  deep-rank must cap this job's verdict at "Weak"; `flags` are human-readable
  reasons surfaced in the UI.
- `assess_eligibility(job: JobListing, candidate_years: float, candidate_region: str = "India") -> EligibilityResult`.
  The caller computes `candidate_years` once (from the profile — parse the first
  `N+ years` in `compose_profile_text().text`, fallback config `DEFAULT_YEARS = 2`)
  and passes it in, keeping this function pure.

Rules:
- **Experience gap.** `required_years = _parse_required_years(job.description)` —
  regex over the JD for `(\d+)\s*\+?\s*years?` (also matches "10 years of exp"),
  taking the **max** stated value; `None` if none found. If `required_years` is
  found and `required_years - candidate_years > _GAP_THRESHOLD` (default **3**) →
  `demote=True`, flag `f"requires {required_years}y experience, profile has ~{candidate_years:.0f}y"`.
  No required-years stated → no penalty (benefit of the doubt).
- **Region acceptance.** If the job signals it excludes the candidate's region —
  a `job.hires_remotely_in` / metadata field present and not containing
  `candidate_region`, or the description matching a "does not accept applications
  from {region}" cue — → `demote=True`, flag
  `f"may not accept applicants from {candidate_region}"`. No region info → no penalty.

`assess_eligibility` never raises; malformed input yields
`EligibilityResult(demote=False, flags=[])`.

## Component 2 — wiring into the deep-rank

`pipeline.py` (the deep-rank step): after a job's base verdict/score is computed,
call `assess_eligibility(job, candidate_years)`. If `demote`, **cap the stored
verdict at "Weak"** (`verdict = "Weak"` when it would otherwise be Strong/Good)
and **append `flags`** to the existing `match_scores.flags` list. `candidate_years`
is computed once per pipeline run. This is the only behavioral change to ranking;
embeddings/LLM scoring are untouched. Applies to jobs from every source.

The dashboard already hides "Weak" by default and shows the flags on the job
detail, so no UI change is required — demoted jobs simply drop out of the default
Strong/Good view with a visible reason if expanded.

## Component 3 — Wellfound source

Wellfound can't be fetched server-side (no public API; GraphQL feed behind login +
bot protection). So, like Naukri, it's **on-demand and session-based** — but via
the browser rather than a cached token.

- **`sources/wellfound_source.py`** — pure normalizer:
  `wellfound_jobs_from_raw(raw: list[dict]) -> list[JobListing]`. Each raw dict
  (title, company, location, salary/comp, skills, required-years text,
  hires-remotely-in, slug) → `JobListing(source="wellfound",
  job_url=f"https://wellfound.com/jobs/{slug}", description=…, …)`. Rows missing a
  usable description/slug are skipped (project rule: every JobListing carries a
  full description). Unit-tested with fixture dicts; no network.
- **`docs/wellfound-ingest-runbook.md`** — the browser-agent procedure: open the
  candidate's logged-in Wellfound search feed (their filters + "native-apply
  only"), read jobs from the **GraphQL response** (`read_network_requests` on
  `wellfound.com/graphql`; fallback: DOM cards via `read_page`), hand them to
  `wellfound_jobs_from_raw`, and POST into the existing ingest path so they flow
  through dedup → embeddings → deep-rank (now eligibility-aware). Not part of the
  unattended background refresh (needs a live login).

`source_registry.py` documents Wellfound as an on-demand browser source (not added
to the auto-refresh fetcher list).

## Data model

No new tables. `match_scores.flags` (existing json list) carries eligibility flags.
If `JobListing` lacks a `hires_remotely_in` field, add an optional one (nullable,
default `None`) so the Wellfound normalizer can carry region info; other sources
leave it `None`.

## Testing

- `eligibility`: required-years parse ("10 years of exp", "5+ years", none →
  None, takes max of multiple); gap over/under threshold; region excluded vs
  present vs unknown; never raises on junk.
- deep-rank wiring: a job with a big gap gets verdict capped to "Weak" + flag
  stored; an eligible job is unchanged.
- `wellfound_source`: fixture raw dicts → correct `JobListing`s; missing
  description/slug skipped; region carried through.
- Existing suite (267 pytest + 37 vitest) stays green.
- Browser extraction is validated by a manual/live run, not unit tests.

## Non-goals (deferred)

Fully-automated (unattended) Wellfound fetching; hard-dropping ineligible jobs;
visa/location eligibility (already in deep-rank); parsing required years from
unusual phrasings ("a decade of…"); a UI toggle to show demoted jobs (they're in
"Weak" already); editing the gap threshold in the UI (config constant for now).
