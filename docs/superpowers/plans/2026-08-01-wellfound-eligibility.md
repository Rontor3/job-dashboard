# Wellfound Source + Eligibility Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Checkbox steps. Dispatch prompts in caveman style (project memory).

**Goal:** Down-rank jobs the candidate isn't eligible for (big experience gap or region not accepted) to "Weak Fit" so valid jobs surface at the top, uniformly across all sources; plus a Wellfound source that normalizes browser-ingested Wellfound jobs into the pipeline.

**Architecture:** New pure `match/eligibility.py` (`assess_eligibility` + years parsing) — no I/O. It folds into the deep-rank at the `rank_io.py record` step: when an LLM evaluation is written, an ineligible job's `verdict` is capped to `"Weak Fit"` and an eligibility flag is stored. New `sources/wellfound_source.py` normalizer turns raw Wellfound job dicts into `JobListing`s; a runbook covers the browser extraction. No new DB tables.

**Tech Stack:** Python 3.11+, pytest. Verdict vocabulary (existing `db.VALID_VERDICTS`): `Strong Fit`, `Good Fit`, `Moderate Fit`, `Weak Fit`, `Poor Fit`.

## Global Constraints

- **Down-rank, never drop.** Ineligible → cap `verdict` at `"Weak Fit"` (which the dashboard hides by default) + a human-readable flag. Never removes a job.
- **Rules = (1) experience gap, (2) region acceptance** only. Not visa/location/work-mode (already in the deep-rank). Missing info → no penalty (benefit of the doubt).
- Gap is **strong**: `required_years - candidate_years > _GAP_THRESHOLD` (default 3) demotes.
- `assess_eligibility` is pure and NEVER raises; junk input → `EligibilityResult(demote=False, flags=[])`.
- Applies to **all sources** (runs in the shared `record` path).
- Region parsed from the job **description text** (no schema change); the Wellfound normalizer embeds region/years into the description so they're parseable.
- Existing suite (267 pytest + 37 vitest) stays green.

---

### Task 1: `match/eligibility.py` — pure eligibility assessment

**Files:** Create `src/job_dashboard/match/eligibility.py`; Test `tests/test_eligibility.py`.

**Interfaces:**
- `EligibilityResult(demote: bool, flags: list[str])` (dataclass).
- `parse_required_years(text: str) -> float | None` — max `(\d+)\s*\+?\s*years?` in text (matches "10 years of exp", "5+ years"); None if absent.
- `candidate_years_from_profile(profile_text: str, default: float = 2.0) -> float` — first `(\d+)\s*\+?\s*years?` in the profile, else `default`.
- `assess_eligibility(description: str, candidate_years: float, candidate_region: str = "India", gap_threshold: float = 3.0) -> EligibilityResult`.

- [ ] **Step 1 — failing tests:**

```python
# tests/test_eligibility.py
from job_dashboard.match.eligibility import (
    EligibilityResult, parse_required_years, candidate_years_from_profile,
    assess_eligibility,
)


def test_parse_required_years_variants():
    assert parse_required_years("10 years of exp") == 10
    assert parse_required_years("Looking for 5+ years in ML") == 5
    assert parse_required_years("3 to 7 years experience") == 7  # max
    assert parse_required_years("no numbers here") is None


def test_candidate_years_from_profile():
    assert candidate_years_from_profile("Data Scientist with 2+ years building ML") == 2
    assert candidate_years_from_profile("no years mentioned", default=1.5) == 1.5


def test_big_gap_demotes():
    r = assess_eligibility("Requires 10 years of experience.", candidate_years=2)
    assert isinstance(r, EligibilityResult) and r.demote
    assert any("10" in f and "experience" in f.lower() for f in r.flags)


def test_small_gap_does_not_demote():
    # requires 5, candidate 2 -> gap 3, not > threshold 3
    assert assess_eligibility("5+ years required", candidate_years=2).demote is False


def test_no_required_years_no_demote():
    assert assess_eligibility("Great ML role, join us!", candidate_years=2).demote is False


def test_region_excluded_demotes():
    r = assess_eligibility("Remote. Hires remotely in: United States only.",
                           candidate_years=2, candidate_region="India")
    assert r.demote and any("India" in f for f in r.flags)


def test_region_present_ok():
    r = assess_eligibility("Hires remotely in: India, United States.",
                           candidate_years=20, candidate_region="India")
    assert r.demote is False  # region present, no year gap


def test_never_raises_on_junk():
    assert assess_eligibility(None, candidate_years=None).demote is False
```

- [ ] **Step 2 — run → FAIL. Step 3 — implement:**

```python
"""Pure, side-effect-free eligibility assessment (no DB/network).

Down-ranks (never drops) a job when the candidate clearly can't clear a hard
bar: a large required-experience gap, or a stated region the candidate isn't in.
Missing info -> no penalty. NEVER raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_YEARS_RE = re.compile(r"(\d+)\s*\+?\s*years?", re.IGNORECASE)
# "Hires remotely in: <list>" / "accepts applications from <list>"
_HIRES_IN_RE = re.compile(
    r"(?:hires remotely in|accepts? applications? from|open to candidates in)\s*[:\-]?\s*([^.\n]+)",
    re.IGNORECASE,
)


@dataclass
class EligibilityResult:
    demote: bool = False
    flags: list[str] = field(default_factory=list)


def parse_required_years(text) -> float | None:
    if not isinstance(text, str):
        return None
    nums = [int(m) for m in _YEARS_RE.findall(text)]
    return float(max(nums)) if nums else None


def candidate_years_from_profile(profile_text, default: float = 2.0) -> float:
    y = parse_required_years(profile_text if isinstance(profile_text, str) else "")
    return y if y is not None else float(default)


def assess_eligibility(description, candidate_years, candidate_region: str = "India",
                       gap_threshold: float = 3.0) -> EligibilityResult:
    try:
        text = description if isinstance(description, str) else ""
        cyears = float(candidate_years) if candidate_years is not None else 0.0
        flags: list[str] = []
        demote = False

        req = parse_required_years(text)
        if req is not None and (req - cyears) > gap_threshold:
            demote = True
            flags.append(f"requires {req:.0f}y experience, profile has ~{cyears:.0f}y")

        region = (candidate_region or "").strip().lower()
        for m in _HIRES_IN_RE.finditer(text):
            listed = m.group(1).lower()
            if region and region not in listed:
                demote = True
                flags.append(f"may not accept applicants from {candidate_region}")
                break

        return EligibilityResult(demote=demote, flags=flags)
    except Exception:
        return EligibilityResult(demote=False, flags=[])
```

- [ ] **Step 4 — PASS (8). Step 5 — commit** `feat: pure eligibility assessment (experience-gap + region), down-rank only`.

---

### Task 2: wire eligibility into the deep-rank `record` path

**Files:** Modify `src/job_dashboard/rank_io.py`; Test `tests/test_rank_eligibility.py`.

**Interfaces:**
- New helper in `rank_io.py`: `apply_eligibility(job, payload, candidate_years) -> dict` — returns a copy of `payload` with `verdict` capped to `"Weak Fit"` and an eligibility entry added to `flags` when `assess_eligibility(job.get("description",""), candidate_years).demote`. `job` is a `job_detail` dict; `flags` in the payload is a dict — add under key `"eligibility"` (a list). If `flags` isn't a dict, wrap it.
- `record` command: after loading `payload`, fetch `job_detail(conn, job_id)`; compute `candidate_years` once via `candidate_years_from_profile(compose_profile_text().text)` (tolerate any failure → default 2.0); `payload = apply_eligibility(detail, payload, candidate_years)` before `record_llm_evaluation`.

- [ ] **Step 1 — failing tests:**

```python
# tests/test_rank_eligibility.py
from job_dashboard.rank_io import apply_eligibility


def test_big_gap_caps_verdict_to_weak_fit():
    job = {"description": "Senior role. Requires 10 years of experience."}
    payload = {"verdict": "Strong Fit", "flags": {}, "strengths": [], "gaps": []}
    out = apply_eligibility(job, payload, candidate_years=2)
    assert out["verdict"] == "Weak Fit"
    assert out["flags"]["eligibility"] and "10" in out["flags"]["eligibility"][0]
    # original payload not mutated
    assert payload["verdict"] == "Strong Fit"


def test_eligible_job_unchanged():
    job = {"description": "ML engineer, 2+ years, hires remotely in India."}
    payload = {"verdict": "Strong Fit", "flags": {}}
    out = apply_eligibility(job, payload, candidate_years=2)
    assert out["verdict"] == "Strong Fit"
    assert "eligibility" not in out.get("flags", {})


def test_non_dict_flags_wrapped():
    job = {"description": "Requires 12 years experience."}
    out = apply_eligibility(job, {"verdict": "Good Fit", "flags": None}, candidate_years=2)
    assert out["verdict"] == "Weak Fit" and isinstance(out["flags"], dict)
```

- [ ] **Step 2 — FAIL. Step 3 — implement** `apply_eligibility` (deep-copy payload; `assess_eligibility`; on demote set `verdict="Weak Fit"` and `flags["eligibility"]=result.flags`, coercing non-dict flags to `{}` first, preserving other flag keys). Wire it into the `record` command with the `candidate_years` computation guarded by try/except. Keep `main`'s existing error handling.
- [ ] **Step 4 — PASS; full suite green. Step 5 — commit** `feat: deep-rank record path down-ranks ineligible jobs to Weak Fit`.

---

### Task 3: `sources/wellfound_source.py` — normalizer

**Files:** Create `src/job_dashboard/sources/wellfound_source.py`; Test `tests/test_wellfound_source.py`.

**Interfaces:** `wellfound_jobs_from_raw(raw: list[dict]) -> list[JobListing]`. Each raw dict has keys like `{slug, title, company, location, remote (bool), salary, skills (list), years_experience (int|str), hires_remotely_in (str), description}`. Produces `JobListing(source="wellfound", job_url=f"https://wellfound.com/jobs/{slug}", title, company, description=<composed>, location, is_remote, salary_text, external_id=slug)`. **Composed description** embeds the JD plus a normalized tail so eligibility can parse it: append `f"\n\n{years_experience} years of exp" ` when present and `f"\nHires remotely in: {hires_remotely_in}"` when present. Rows missing `title`/`company`/`slug` OR with no description text (after compose) are skipped (project rule). Never raises on a bad row (skip it).

- [ ] **Step 1 — failing tests:**

```python
# tests/test_wellfound_source.py
from job_dashboard.sources.wellfound_source import wellfound_jobs_from_raw
from job_dashboard.models import JobListing


def test_normalizes_a_row_with_years_and_region_in_description():
    raw = [{
        "slug": "4521063-lead-data-scientist", "title": "Lead Data Scientist / AI/ML Engineer",
        "company": "talentxo", "location": "Pune", "remote": True,
        "salary": "₹50L – ₹55L", "skills": ["Python", "Fraud"],
        "years_experience": 10, "hires_remotely_in": "India",
        "description": "Build production ML for fraud detection.",
    }]
    jobs = wellfound_jobs_from_raw(raw)
    assert len(jobs) == 1
    j = jobs[0]
    assert isinstance(j, JobListing) and j.source == "wellfound"
    assert j.job_url == "https://wellfound.com/jobs/4521063-lead-data-scientist"
    assert j.company == "talentxo"
    assert "10 years of exp" in j.description and "Hires remotely in: India" in j.description


def test_skips_rows_without_slug_or_description():
    raw = [
        {"title": "X", "company": "Y", "description": "d"},          # no slug
        {"slug": "s", "company": "Y", "description": "d"},           # no title
        {"slug": "s2", "title": "T", "company": "Y"},               # no description
    ]
    assert wellfound_jobs_from_raw(raw) == []


def test_bad_row_does_not_raise():
    assert wellfound_jobs_from_raw([None, 42, {"slug": "s", "title": "T",
                                               "company": "C", "description": "hi"}])
```

- [ ] **Step 2 — FAIL. Step 3 — implement** the normalizer (compose description tail with years/region; skip incomplete rows; per-row try/except). **Step 4 — PASS; full suite green. Step 5 — commit** `feat: Wellfound source normalizer (raw feed -> JobListing)`.

---

### Task 4: ingest runbook + registry note + live e2e + finish

- [ ] Write `docs/wellfound-ingest-runbook.md`: browser-agent procedure — open the candidate's logged-in Wellfound search feed (their filters + "native-apply only"); read jobs from the GraphQL response (`read_network_requests` on `wellfound.com/graphql`; fallback DOM via `read_page`/`get_page_text`); map to the raw-dict shape; `wellfound_jobs_from_raw`; POST into the existing ingest path; then `/rank` (eligibility-aware). On-demand only (needs login) — restate that it's not in the unattended refresh.
- [ ] In `source_registry.py`, add a short comment block documenting Wellfound as an on-demand browser source (do NOT add it to the auto-refresh fetcher list).
- [ ] Live/manual e2e (controller-driven, with the user + Claude-in-Chrome): extract a handful of real Wellfound jobs → normalize → ingest → confirm they appear; run `/rank`; confirm a 10y-requirement job lands in "Weak Fit" with the eligibility flag while a matching job stays Strong/Good. Screenshot. Ledger.
- [ ] Whole-branch review + finishing-a-development-branch.

## Not covered (spec non-goals)

Unattended Wellfound fetching; hard-dropping ineligible jobs; visa/location eligibility (deep-rank already); a UI toggle for demoted jobs; UI-editable gap threshold.
