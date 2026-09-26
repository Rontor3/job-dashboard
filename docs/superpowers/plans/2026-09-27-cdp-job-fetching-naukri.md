# CDP Job Fetching: Naukri Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh also fetches new Naukri jobs (relevance order, last 24h, few pages per term, near-duplicates collapsed) through the existing CDP framework, behind an off-by-default switch.

**Architecture:** A new `sources/cdp/naukri.py` adapter with the same shape as `linkedin.py` (`run(session, ctx) -> list[JobListing]`), registered in `runner.py`. Everything is read **passively**: loading `https://www.naukri.com/<term>-jobs[-N]?jobAge=D` makes the page fire `jobapi/v3/search` itself; loading a job page makes it fire `jobapi/v4/job/<id>` (full description). No replayed API calls, no clicks. Task 1 first generalises the runner (per-site windows, limits, enable flags, text-duplicate check).

**Tech Stack:** Python 3, sqlite3, existing `CdpSession` (`goto` + `capture`), FastAPI, pytest. Spec: `docs/career-agent/2026-09-25-cdp-job-fetching-design.md` (Naukri section + "Live check 2026-09-27"). Prior plan/framework: `docs/superpowers/plans/2026-09-26-cdp-job-fetching-framework-linkedin.md`.

## Global Constraints

- Run tests: `PYTHONPATH=src python3 -m pytest tests/<file> -q`. Tests never touch a browser/network; only Task 5 does, gated by `RUN_CDP_TESTS=1`.
- `browser_naukri_enabled` defaults to `"0"`. 48h minimum interval per site (existing `browser_min_interval_hours`).
- Read passively only: **never replay `jobapi/*` calls** (replaying `v3/search` from the tab caused `406 recaptcha` after ~16 calls in research). **Any captured response with status 403, 406 or 429 raises `Blocked`**, aborts the site, is recorded in `fetch_state.last_error`, never retried in the same run and, via the existing cooldown, not on the next Refresh.
- No login, no captcha solving, no clicks, never open `applyRedirectUrl`/`companyApplyUrl`, never touch Apply.
- Pacing 6-12 s (existing `CdpSession` nap); caps: incremental 40 loads, backfill 80 loads.
- Order is **relevance** (no `sort=f`): it is not date-monotonic, so there is **no stop-after-known**; depth is bounded by `max_pages` (incremental 5, backfill 5 with `jobAge=30`).
- Naukri `createdDate` is the last **renew** time. A known job with a newer `createdDate` is a repost: move `posted_date` forward via `ctx.redate` (never backward), do not re-insert.
- Near-duplicates (consultancies post the same job under many `jobId`s) are collapsed on normalized title+company+location **before any detail load**, within the run and against jobs already in the DB.
- Terms: `machine learning engineer`, `data scientist`, `ai engineer`, `llm engineer`.
- Files < 500 lines. Commits: stage only files named in each task (other sessions have uncommitted edits — never `git add -A`).

## Verified payload shapes (live, 2026-09-27)

- Search response (`.../jobapi/v3/search?...&pageNo=N&jobAge=D...`): `{"noOfJobs": int, "jobDetails": [ {jobId, title, companyName, createdDate(ms), jdURL, jobDescription(snippet, 26–3400 chars), companyApplyJob(bool), applyRedirectUrl, companyApplyUrl, placeholders:[{type:"experience"|"salary"|"location", label}], tagsAndSkills, questionnaireIdPresent, ...} ]}`. 20 jobs/page.
- Detail response (`.../jobapi/v4/job/<id>?...`): `{"jobDetails": {jobId, title, description(HTML, full), ...}, ...}`. Same `jobId` as the list (12 digits, first six DDMMYY).
- Canonical URL: `https://www.naukri.com` + `jdURL` (tracking-free).
- Search URL: `https://www.naukri.com/<term-dashes>-jobs` for page 1, `-jobs-<N>` for N ≥ 2, plus `?jobAge=<1|3|7|15|30>`.
- Consultancy near-duplicates verified: 20 of 20 rows on one page were one job under 20 ids.

## File Structure

| File | Responsibility |
|---|---|
| `src/job_dashboard/sources/cdp/naukri.py` | URL, parsing, collapse key, `to_listing`, `run` |
| `src/job_dashboard/sources/cdp/runner.py` | register Naukri; per-site windows/limits; `known_text` |
| `src/job_dashboard/sources/cdp/types.py` | `AdapterContext.known_text` |
| `src/job_dashboard/qa_store.py`, `api/qa_routes.py` | `browser_naukri_enabled` setting + API |
| `tests/test_cdp_naukri_parse.py`, `tests/test_cdp_naukri_run.py`, extend `tests/test_cdp_runner.py`, `tests/test_cdp_settings_api.py`, `tests/test_cdp_live_naukri.py` | tests |

---

### Task 1: Generalise runner (per-site windows, limits, text-duplicate check, enable flag)

**Files:**
- Modify: `src/job_dashboard/sources/cdp/types.py`, `runner.py`, `src/job_dashboard/qa_store.py`, `src/job_dashboard/api/qa_routes.py`
- Test: extend `tests/test_cdp_runner.py`, `tests/test_cdp_settings_api.py`

**Interfaces:**
- Produces: `AdapterContext.known_text: Optional[Callable[[str, str, str], bool]] = None` `(title, company, location) -> a same-source job with the same normalized text exists`; `runner.WINDOWS = {"linkedin": (24, 48, 168, 720)}` (hours; Naukri added in Task 4); `runner.LIMITS_BY_SITE: dict[site, dict[mode, (max_pages, load_cap, stop_after_known)]]` falling back to the existing `LIMITS`; `_window(mode, row, now, windows)`; `DEFAULT_SETTINGS["browser_naukri_enabled"] = "0"`; settings API get/put `browser_naukri_enabled`.

- [ ] **Step 1: Failing tests** (append)

```python
# tests/test_cdp_runner.py
def test_known_text_matches_normalized_title_company_location():
    c = conn(); c.execute("ALTER TABLE jobs ADD COLUMN title TEXT"); c.execute("ALTER TABLE jobs ADD COLUMN company TEXT")
    c.execute("ALTER TABLE jobs ADD COLUMN location TEXT")
    c.execute("INSERT INTO jobs (source, external_id, job_url, title, company, location) "
              "VALUES ('linkedin','7','u7','Data  Scientist','Consult Asia','Bengaluru')"); c.commit()
    got = {}
    def run(s, ctx):
        got["dup"] = ctx.known_text(" data scientist ", "CONSULT ASIA", "bengaluru")
        got["other_city"] = ctx.known_text("Data Scientist", "Consult Asia", "Pune")
        return []
    go(c, run)
    assert got == {"dup": True, "other_city": False}


def test_window_uses_the_sites_own_buckets():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    row = {"last_success_at": (now - timedelta(hours=100)).isoformat()}
    assert runner._window("incremental", row, now, (24, 72, 168, 360, 720)) == 168
    assert runner._window("incremental", None, now, (24, 72, 168, 360, 720)) == 72
    assert runner._window("backfill", None, now, (24, 72, 168, 360, 720)) == 720
```
```python
# tests/test_cdp_settings_api.py (append)
def test_naukri_switch_roundtrip(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    assert c.get("/api/agent-settings").json()["browser_naukri_enabled"] is False
    assert c.put("/api/agent-settings", json={"browser_naukri_enabled": True}).status_code == 200
    assert c.get("/api/agent-settings").json()["browser_naukri_enabled"] is True
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is False
```
Note the existing runner tests call `_window(mode, row, now)` only through `fetch_browser_sources`; keep the fetch call sites working.

- [ ] **Step 2:** Run both files → FAIL.

- [ ] **Step 3: Implement**

`types.py`: add to `AdapterContext` (before `hours`): `known_text: Optional[Callable[[str, str, str], bool]] = None`.

`qa_store.py`: add `"browser_naukri_enabled": "0"` to `DEFAULT_SETTINGS`.

`qa_routes.py`: `SettingsBody.browser_naukri_enabled: Optional[bool] = None`; in `get_settings` and the `put_settings` response add `"browser_naukri_enabled": qa_store.get_setting(conn, "browser_naukri_enabled") == "1"`; in `put_settings` handle it exactly like the LinkedIn flag.

`runner.py`:
```python
WINDOWS = {"linkedin": tuple(sorted(linkedin.TPR))}
LIMITS_BY_SITE = {}          # site -> {mode: (max_pages, load_cap, stop_after_known)}; missing -> LIMITS
```
in `fetch_browser_sources`: `pages, cap, stop_known = LIMITS_BY_SITE.get(site, LIMITS)[mode]`; build `AdapterContext(..., known_text=_known_text_fn(conn, site), hours=_window(mode, state.get(conn, site), now, WINDOWS.get(site, WINDOWS["linkedin"])))`. Change `_window`:
```python
def _window(mode, row, now, windows):
    """Incremental look-back: at least the smallest bucket >= 48h, widened to cover the gap since the last success."""
    if mode == "backfill":
        return max(windows)
    floor = next((b for b in windows if b >= 48), max(windows))
    last = (row or {}).get("last_success_at")
    if not last:
        return floor
    h = max(48, ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(last)).total_seconds() / 3600)
    return next((b for b in windows if b >= h), max(windows))
```
and
```python
def _norm(s):
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (s or "").lower()).split())


def _known_text_fn(conn, site):
    def known_text(title, company, location):
        want = (_norm(title), _norm(company), _norm(location))
        return any((_norm(t), _norm(c), _norm(l)) == want for t, c, l in conn.execute(
            "SELECT title, company, location FROM jobs WHERE source=? AND LOWER(company)=LOWER(?)", (site, company or "")))
    return known_text
```
(`_norm` is exported for the adapter's in-run collapse: Task 2 imports it as `from job_dashboard.sources.cdp.runner import ...` would be circular, so put `_norm` in `types.py` as `norm_text` and import it in both; update the snippet accordingly.) In the test conn helper the `jobs` table lacks title/company/location for older tests: `_known_text_fn` is only built lazily and never invoked in those tests, so no change is needed to existing tests.

- [ ] **Step 4:** Run `tests/test_cdp_runner.py tests/test_cdp_settings_api.py tests/test_qa_api.py tests/test_pipeline_browser.py -q` → PASS.
- [ ] **Step 5: Commit** — `git add src/job_dashboard/sources/cdp/types.py src/job_dashboard/sources/cdp/runner.py src/job_dashboard/qa_store.py src/job_dashboard/api/qa_routes.py tests/test_cdp_runner.py tests/test_cdp_settings_api.py`; message `feat(cdp): per-site windows/limits, text-duplicate check, naukri enable flag`.

---

### Task 2: Naukri parsing (pure functions)

**Files:** Create `src/job_dashboard/sources/cdp/naukri.py` (parsing half); Test `tests/test_cdp_naukri_parse.py`

**Interfaces:**
- Produces: `SITE = "naukri"`; `TERMS`; `AGES = {24: 1, 72: 3, 168: 7, 360: 15, 720: 30}` (hours → `jobAge`); `search_url(term, hours, page=1) -> str`; `job_url(card_or_jdurl) -> str`; `parse_search(body) -> (list[card], total|None)`; `parse_detail(body) -> {"description": str, "job_id": str} | None`; `collapse_key(card) -> str`; `html_to_text(html) -> str`; `to_listing(card, description) -> JobListing`.
- Card dict keys: `id,title,company,location,salary,posted_ms,jd_url,external,apply_url,snippet`.

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_naukri_parse.py
from job_dashboard.sources.cdp import naukri as nk

def D(i, title="Data Scientist", company="Acme", ext=False, **kw):
    d = {"jobId": str(i), "title": title, "companyName": company, "createdDate": 1790000000000,
         "jdURL": f"/job-listings-x-{i}?src=abc", "jobDescription": "<b>Snip</b> pet", "companyApplyJob": ext,
         "applyRedirectUrl": "https://acme.com/apply" if ext else None,
         "placeholders": [{"type": "experience", "label": "3-6 Yrs"}, {"type": "salary", "label": "Not disclosed"},
                          {"type": "location", "label": "Bengaluru"}]}
    d.update(kw); return d

SEARCH = {"noOfJobs": 1967, "jobDetails": [D(1), D(2, ext=True), {"title": "no id"}]}
DETAIL = {"jobDetails": {"jobId": "2", "description": "<p>Build <b>models</b></p><ul><li>Python</li></ul>&amp; more"}}


def test_parse_search():
    cards, total = nk.parse_search(SEARCH)
    assert total == 1967 and [c["id"] for c in cards] == ["1", "2"]
    c = cards[1]
    assert c["external"] is True and c["apply_url"] == "https://acme.com/apply"
    assert c["location"] == "Bengaluru" and c["salary"] is None          # "Not disclosed" dropped
    assert c["jd_url"] == "/job-listings-x-2"                            # query string stripped


def test_parse_detail_and_html_to_text():
    d = nk.parse_detail(DETAIL)
    assert d["job_id"] == "2" and "Build models" in d["description"] and "Python" in d["description"]
    assert "<" not in d["description"] and "& more" in d["description"]
    assert nk.parse_detail({"nope": 1}) is None


def test_to_listing_native_and_external():
    cards, _ = nk.parse_search(SEARCH)
    n, e = nk.to_listing(cards[0], "desc"), nk.to_listing(cards[1], "desc")
    assert (n.source, n.external_id, n.job_url) == ("naukri", "1", "https://www.naukri.com/job-listings-x-1")
    assert (n.apply_kind, n.apply_url) == ("native", None)
    assert (e.apply_kind, e.apply_url) == ("external", "https://acme.com/apply")
    assert n.posted_date.startswith("2026-") and n.location == "Bengaluru"


def test_collapse_key_ignores_case_spacing_and_punctuation():
    a, b, c = (nk.parse_search({"jobDetails": [D(i, title=t, company=co)]})[0][0] for i, t, co in
               [(1, "Data  Scientist!", "Consult Asia"), (2, "data scientist", "CONSULT ASIA"), (3, "Data Scientist", "Other")])
    assert nk.collapse_key(a) == nk.collapse_key(b) != nk.collapse_key(c)


def test_search_url():
    assert nk.search_url("machine learning engineer", 24) == "https://www.naukri.com/machine-learning-engineer-jobs?jobAge=1"
    assert nk.search_url("ai engineer", 720, page=3) == "https://www.naukri.com/ai-engineer-jobs-3?jobAge=30"
```

- [ ] **Step 2:** FAIL. **Step 3: Implement**

```python
"""Naukri adapter. Reads only the responses Naukri's own pages make (jobapi/v3/search on a search
page, jobapi/v4/job/<id> on a job page). Never replays an API call, never clicks."""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone

from job_dashboard.models import JobListing
from job_dashboard.sources.cdp.types import norm_text

SITE = "naukri"
BASE = "https://www.naukri.com"
TERMS = ["machine learning engineer", "data scientist", "ai engineer", "llm engineer"]
AGES = {24: 1, 72: 3, 168: 7, 360: 15, 720: 30}       # window hours -> jobAge days


def search_url(term: str, hours: int, page: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    return f"{BASE}/{slug}-jobs{'' if page == 1 else f'-{page}'}?jobAge={AGES[hours]}"


def _label(card, kind):
    return next((p.get("label") for p in card.get("placeholders") or [] if p.get("type") == kind), None)


def parse_search(body):
    out = []
    for d in body.get("jobDetails") or []:
        if not d.get("jobId") or not d.get("title") or not d.get("jdURL"):
            continue
        salary = _label(d, "salary")
        ext = bool(d.get("companyApplyJob"))
        out.append(dict(
            id=str(d["jobId"]), title=d["title"], company=d.get("companyName") or "",
            location=_label(d, "location"), salary=None if not salary or salary.lower() == "not disclosed" else salary,
            posted_ms=d.get("createdDate"), jd_url=d["jdURL"].split("?")[0], external=ext,
            apply_url=d.get("applyRedirectUrl") if ext else None, snippet=d.get("jobDescription") or ""))
    return out, body.get("noOfJobs")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", s or "")
    s = _html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", s)).strip()


def parse_detail(body):
    d = body.get("jobDetails")
    if not isinstance(d, dict) or not d.get("description") or not d.get("jobId"):
        return None
    return {"job_id": str(d["jobId"]), "description": html_to_text(d["description"])}


def collapse_key(card) -> str:
    return "|".join(norm_text(card.get(k)) for k in ("title", "company", "location"))


def job_url(jd_url: str) -> str:
    return BASE + jd_url


def to_listing(card, description) -> JobListing:
    ms = card.get("posted_ms")
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card["company"],
        location=card.get("location"), job_url=job_url(card["jd_url"]), description=description,
        salary_text=card.get("salary"),
        posted_date=datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None,
        apply_url=card.get("apply_url"), apply_kind="external" if card.get("external") and card.get("apply_url") else
        ("unknown" if card.get("external") else "native"))
```
`types.py` gains `norm_text` (moved from Task 1's `_norm`):
```python
def norm_text(s):
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (s or "").lower()).split())
```
- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `git add src/job_dashboard/sources/cdp/naukri.py tests/test_cdp_naukri_parse.py` (+ `types.py` if `norm_text` was added here instead of Task 1); message `feat(cdp): Naukri search/detail parsing and JobListing mapping`.

---

### Task 3: Naukri adapter `run(session, ctx)`

**Files:** Modify `naukri.py` (append); Test `tests/test_cdp_naukri_run.py`

**Interfaces:**
- Consumes: `session.goto`, `session.capture(*needles)` → `.responses` (each has `.status`, `.url`) and `.bodies()`; `AdapterContext(mode, known, terms, max_pages, stop_after_known, redate, known_text, hours, stats)`; `Blocked`, `CapReached`.
- Behaviour of `run`:
  - `hours = 720 if backfill else ctx.hours`. Phase 1, per term, per page `1..ctx.max_pages`: `_search(session, url)`; a page returning no cards ends that term (also if its `total` is 0).
  - `_search`: capture `jobapi/v3/search`; if any captured response status ∈ {403, 406, 429} → `raise Blocked`; if **nothing** was captured, reload once (the site sometimes fires nothing on a cold load); if still nothing → return `[]`.
  - Per card: skip ids already seen this run; skip cards with no company; `ctx.known(id, job_url)` → `skipped_known += 1` and, if `posted_ms` present, `ctx.redate(id, url, iso)` (count `stats["redated"]`); else `ctx.known_text(title, company, location)` or an in-run `collapse_key` already seen → `stats["collapsed"] += 1`, skip; else queue for detail.
  - Phase 2 (details), round-robin across terms: `session.goto(job_url)`, capture `jobapi/v4/job/`; same Blocked status check; `parse_detail(...)` matching the card id → `to_listing`; no description → skip (retried next run, not known).
  - `CapReached` → `ctx.stats["capped"] = True`, return what was collected. `stats["pages"]` counts search pages that returned cards.

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_naukri_run.py
import pytest
from job_dashboard.sources.cdp import naukri as nk
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, FakeResponse, make_session
from tests.test_cdp_naukri_parse import D

S_URL = "https://www.naukri.com/jobapi/v3/search?pageNo=1"
V_URL = "https://www.naukri.com/jobapi/v4/job/1?microsite=y"


def ctx(known=(), text=(), **kw):
    base = dict(mode="incremental", known=lambda i, u: i in known, terms=["data scientist"], max_pages=2,
                stop_after_known=10, hours=24, known_text=lambda t, c, l: (t, c, l) in text)
    return AdapterContext(**{**base, **kw})


def search_page(term, ids_titles, page=1, hours=24):
    return {nk.search_url(term, hours, page): [(S_URL, {"noOfJobs": 99, "jobDetails": [D(i, title=t) for i, t in ids_titles]})]}


def detail_script(*ids):
    return {nk.job_url(f"/job-listings-x-{i}"): [(V_URL, {"jobDetails": {"jobId": str(i), "description": f"<p>full {i}</p>"}})]
            for i in ids}


def test_new_job_gets_detail_description_and_known_is_skipped():
    script = {**search_page("data scientist", [(1, "A"), (2, "B")]), **search_page("data scientist", [], 2), **detail_script(1)}
    page = FakePage(script)
    c = ctx(known={"2"}); c.redate = lambda *a: True
    with make_session(page) as s:
        out = nk.run(s, c)
    assert [(j.external_id, j.description) for j in out] == [("1", "full 1")]
    assert c.stats["skipped_known"] == 1 and c.stats["redated"] == 1


def test_near_duplicates_collapse_within_run_and_against_db():
    # 3 cards: two identical title/company/location, one already in DB text-wise
    script = {**search_page("data scientist", [(1, "Data Scientist"), (2, "data  scientist"), (3, "Other Role")]),
              **search_page("data scientist", [], 2), **detail_script(1, 3)}
    text = {("Other Role", "Acme", "Bengaluru")}
    c = ctx(text=text)
    with make_session(FakePage(script)) as s:
        out = nk.run(s, c)
    assert [j.external_id for j in out] == ["1"] and c.stats["collapsed"] == 2


def test_details_are_loaded_round_robin_after_all_searches():
    script = {}
    for t in ("a", "b"):
        script.update(search_page(t, [(1 if t == "a" else 2, "T")]))
        script.update(search_page(t, [], 2))
    script.update(detail_script(1, 2))
    page = FakePage(script)
    with make_session(page) as s:
        nk.run(s, ctx(terms=["a", "b"], text=set()))
    urls = [u for u in page.visited if "/job-listings" in u]
    assert page.visited.index(urls[0]) > max(i for i, u in enumerate(page.visited) if "-jobs" in u and "job-listings" not in u)


@pytest.mark.parametrize("status", [403, 406, 429])
def test_blocked_status_on_api_response_aborts(status):
    class P(FakePage):
        def goto(self, url, wait_until=None):
            r = super().goto(url, wait_until)
            for h in list(self.handlers):
                h(FakeResponse("https://www.naukri.com/jobapi/v3/search?x", {}, status=status))
            return r
    with make_session(P()) as s:
        with pytest.raises(Blocked):
            nk.run(s, ctx())


def test_silent_first_load_is_reloaded_once():
    u = nk.search_url("data scientist", 24)
    class P(FakePage):
        n = 0
        def goto(self, url, wait_until=None):
            if url == u:
                P.n += 1
                if P.n == 1:                       # first load fires nothing
                    self.url = url; self.visited.append(url); return FakeResponse(url, None)
            return super().goto(url, wait_until)
    page = P({**search_page("data scientist", [(1, "A")]), **search_page("data scientist", [], 2), **detail_script(1)})
    with make_session(page) as s:
        assert [j.external_id for j in nk.run(s, ctx())] == ["1"]
    assert page.visited.count(u) == 2


def test_cap_returns_partial_and_sets_capped():
    script = {**search_page("data scientist", [(1, "A")]), **detail_script(1)}
    c = ctx()
    with make_session(FakePage(script), max_loads=1) as s:
        assert nk.run(s, c) == [] and c.stats["capped"] is True


def test_no_description_anywhere_is_skipped_not_known():
    script = {**search_page("data scientist", [(1, "A")]), **search_page("data scientist", [], 2)}
    c = ctx()
    with make_session(FakePage(script)) as s:
        assert nk.run(s, c) == []
    assert c.stats["skipped_known"] == 0
```
- [ ] **Step 2:** FAIL (`no attribute 'run'`). **Step 3: Implement** (append to `naukri.py`; add `from job_dashboard.sources.cdp.types import Blocked, CapReached`, `norm_text` at the top import block):

```python
_BLOCK = (403, 406, 429)


def _captured(session, url, needle):
    with session.capture(needle) as cap:
        session.goto(url)
    if any(getattr(r, "status", 200) in _BLOCK for r in cap.responses):
        raise Blocked(f"HTTP block on {needle}")
    return list(cap.bodies())


def _search(session, url):
    bodies = _captured(session, url, "jobapi/v3/search")
    if not bodies:                                   # cold load sometimes fires nothing: reload once
        bodies = _captured(session, url, "jobapi/v3/search")
    cards = []
    for _, b in bodies:
        cards.extend(parse_search(b)[0])
    return cards


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def run(session, ctx):
    hours = 720 if ctx.mode == "backfill" else ctx.hours
    seen_ids, seen_text, pending, found = set(), set(), {}, {}
    ctx.stats.setdefault("collapsed", 0)
    try:
        for term in ctx.terms:
            queue = pending.setdefault(term, [])
            for p in range(1, ctx.max_pages + 1):
                cards = _search(session, search_url(term, hours, p))
                if not cards:
                    break
                ctx.stats["pages"] += 1
                for c in cards:
                    if c["id"] in seen_ids or not c["company"]:
                        continue
                    seen_ids.add(c["id"])
                    url = job_url(c["jd_url"])
                    if ctx.known(c["id"], url):
                        ctx.stats["skipped_known"] += 1
                        if ctx.redate and c.get("posted_ms") and ctx.redate(c["id"], url, _iso(c["posted_ms"])):
                            ctx.stats["redated"] = ctx.stats.get("redated", 0) + 1
                        continue
                    key = collapse_key(c)
                    if key in seen_text or (ctx.known_text and ctx.known_text(c["title"], c["company"], c["location"] or "")):
                        ctx.stats["collapsed"] += 1
                        continue
                    seen_text.add(key)
                    queue.append(c)
        queues = [q for q in pending.values() if q]
        while queues:
            for q in list(queues):
                c = q.pop(0)
                for _, body in _captured(session, job_url(c["jd_url"]), "jobapi/v4/job/"):
                    d = parse_detail(body)
                    if d and d["job_id"] == c["id"]:
                        found[c["id"]] = to_listing(c, d["description"])
                if not q:
                    queues.remove(q)
    except CapReached:
        ctx.stats["capped"] = True
    return list(found.values())
```
Note: `ctx.known_text` receives `location or ""`; the test lambdas compare the same triple as the card's fields.
- [ ] **Step 4:** Run → PASS (all 9 cases). **Step 5: Commit** `git add src/job_dashboard/sources/cdp/naukri.py tests/test_cdp_naukri_run.py`; message `feat(cdp): Naukri adapter - passive search+detail, near-duplicate collapse, block detection`.

---

### Task 4: Register Naukri in the runner and Refresh

**Files:** Modify `runner.py`; Test extend `tests/test_cdp_runner.py`, `tests/test_pipeline_browser.py`

**Interfaces:** `ADAPTERS["naukri"] = (naukri.run, naukri.TERMS)`; `WINDOWS["naukri"] = tuple(sorted(naukri.AGES))` i.e. `(24, 72, 168, 360, 720)`; `LIMITS_BY_SITE["naukri"] = {"incremental": (5, 40, 10**9), "backfill": (5, 80, 10**9)}`. `state.enabled(conn, "naukri")` already reads `browser_naukri_enabled` (Task 1).

- [ ] **Step 1: Failing tests**
```python
def test_naukri_is_registered_but_off_by_default():
    assert "naukri" in runner.ADAPTERS
    c = conn()                                   # only linkedin enabled by the helper
    _, results = runner.fetch_browser_sources(c, adapters={"naukri": runner.ADAPTERS["naukri"]},
                                              reachable=lambda u: True, session_factory=None)
    assert results == []


def test_naukri_limits_and_windows():
    assert runner.LIMITS_BY_SITE["naukri"]["incremental"] == (5, 40, 10**9)
    assert runner.WINDOWS["naukri"] == (24, 72, 168, 360, 720)
```
- [ ] **Step 2–3:** FAIL → implement the three registrations (import `naukri` alongside `linkedin`).
- [ ] **Step 4:** `tests/test_cdp_runner.py tests/test_pipeline_browser.py tests/test_cdp_naukri_run.py -q` PASS. The RefreshButton already renders any site in `last_result.browser`, so no frontend change.
- [ ] **Step 5: Commit** `feat(cdp): register Naukri adapter, limits and windows`.

---

### Task 5: Gated live smoke

**Files:** Create `tests/test_cdp_live_naukri.py`

- [ ] **Step 1: Write**
```python
import os
import pytest
from job_dashboard.sources.cdp import naukri as nk
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def test_one_term_two_pages_with_details():
    ctx = AdapterContext("incremental", lambda i, u: False, ["data scientist"], max_pages=2, stop_after_known=10**9, hours=24,
                         known_text=lambda t, c, l: False)
    with CdpSession("http://localhost:9222", max_loads=6) as s:
        jobs = nk.run(s, ctx)
    print(len(jobs), "jobs; collapsed", ctx.stats["collapsed"], "; loads", s.loads)
    assert jobs and all(j.title and j.company and len(j.description) > 200 and j.job_url.startswith("https://www.naukri.com/") for j in jobs)
    assert {j.apply_kind for j in jobs} <= {"native", "external", "unknown"}
    assert len({(j.title.lower(), j.company.lower(), (j.location or "").lower()) for j in jobs}) == len(jobs)
```
- [ ] **Step 2:** `RUN_CDP_TESTS=1 PYTHONPATH=src python3 -m pytest tests/test_cdp_live_naukri.py -q -s` — needs the career-agent Chrome on :9222, logged in to Naukri. Expected PASS (~6 loads, no challenge). On failure the message is the finding (payload drift like LinkedIn's on 2026-09-27): fix `parse_*` and the fixtures to the real shape, keep unit tests meaningful, re-run. A `Blocked` here means stop and report; do not retry in a loop.
- [ ] **Step 3: Commit** `test(cdp): gated live Naukri smoke check`.

---

## After the plan: gates (not code)

1. Live smoke passes; enable with `PUT /api/agent-settings {"browser_naukri_enabled": true}`; one Refresh (backfill, `jobAge=30`, ≤ 80 loads).
2. Day-2: Refresh again; compare against `data/research_baselines/naukri_2026-09-25.json` (known ids skipped, only new ones inserted, reposts re-dated, collapse count sane).
3. Deferred: the four recommended feeds; title-only narrowing; per-term depth tuning from measured new-job density.

## Self-review

- **Spec coverage:** passive capture only, never replay (constraints, T3); relevance order + `jobAge` windows (T2/T4); pages per term 5, caps 40/80 (T4); near-duplicate collapse before detail, within run and vs DB (T1 `known_text`, T3); `createdDate` = renew → redate (T3); apply mapping `companyApplyJob`/`applyRedirectUrl` (T2); detail via `jobapi/v4/job` passively (T3, live-verified); block on 403/406/429 (T3); reload-once on silent cold load (T3); off by default (T1); live gate (T5).
- **Placeholders:** none; the snippet in Task 1 about `_norm` is resolved by placing `norm_text` in `types.py` (Task 2 Step 3 shows it) — Task 1 must import it from there, so implement `norm_text` in Task 1 and reference it from Task 2.
- **Type consistency:** `AdapterContext.known_text(title, company, location)`; `parse_search` returns `(cards, total)` cards use `jd_url`/`posted_ms`/`external`; `to_listing(card, description)`; `WINDOWS`/`LIMITS_BY_SITE` keys are site names matching `ADAPTERS`.
