# CDP Job Fetching: Shared Framework + LinkedIn Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh also fetches new jobs from logged-in sites over CDP, skipping jobs already in the DB, starting with a LinkedIn adapter behind an off-by-default switch.

**Architecture:** New package `src/job_dashboard/sources/cdp/`: `types.py` (exceptions, `SiteResult`, `AdapterContext`), `session.py` (the only Playwright user; navigate + listen, no click API), `state.py` (`fetch_state` table, cadence gate, settings), `runner.py` (per-site isolation, mode, state), `linkedin.py` (parse + adapter). `run_pipeline(..., browser_fetch=None)` gets a "browser sources" stage that inserts returned `JobListing`s through the existing `insert_job`. Spec: `docs/career-agent/2026-09-25-cdp-job-fetching-design.md` (read its LinkedIn + retention sections first).

**Tech Stack:** Python 3, sqlite3, Playwright (`connect_over_cdp`, already installed), FastAPI, pytest, React/Vite.

## Global Constraints

- Run tests: `PYTHONPATH=src python3 -m pytest tests/<file> -q`. Tests never touch a real browser or network; only Task 10 does, gated by `RUN_CDP_TESTS=1`.
- Browser fetching is part of normal Refresh, with `browser_min_interval_hours = 48` per site (spec).
- `browser_linkedin_enabled` defaults to `"0"`; nothing hits LinkedIn until it is switched on after the day-2 check against `data/research_baselines/linkedin_2026-09-25.json`.
- Retention: never fetch jobs older than 30 days (`f_TPR` window ≤ `r2592000`); no seen-keys list, skip-known is `external_id`/`job_url` against `jobs`.
- Hard stop on any challenge: `Blocked` aborts that site's run, is recorded in `fetch_state.last_error`, and is never retried in the same run. No captcha solving, no clicking, no form submission, no writes to LinkedIn.
- One own tab per run, closed at end; never close other tabs or Chrome (`browser.close()` on a CDP connection only detaches).
- Pacing 6–12 s between page loads; caps: 30 loads incremental, 60 backfill. Files < 500 lines. No secrets committed; `data/` is gitignored.
- Commits: no `Co-Authored-By` trailer beyond what `.claude/settings.json` sets; stage only the files named in each task (other sessions have uncommitted edits in this repo — never `git add -A`).

## File Structure

| File | Responsibility |
|---|---|
| `src/job_dashboard/sources/cdp/__init__.py` | empty package marker |
| `src/job_dashboard/sources/cdp/types.py` | `Blocked`, `CapReached`, `AdapterContext`, `SiteResult` |
| `src/job_dashboard/sources/cdp/session.py` | `CdpSession`, `Capture`, `cdp_reachable` |
| `src/job_dashboard/sources/cdp/state.py` | `fetch_state` table, `due()`, `record_run()`, `enabled()` |
| `src/job_dashboard/sources/cdp/runner.py` | `fetch_browser_sources(conn, adapters=..., session_factory=...)` |
| `src/job_dashboard/sources/cdp/linkedin.py` | `parse_cards`, `parse_details`, `search_url`, `to_listing`, `run(session, ctx)` |
| `tests/cdp_fakes.py` | `FakePage`, `FakeResponse`, `make_session` |
| `tests/test_cdp_*.py` | one test file per module |
| modify `src/job_dashboard/models.py`, `db.py`, `pipeline.py`, `api/refresh_job.py`, `api/qa_routes.py`, `qa_store.py`, `match/apply_type.py`, `api/app.py`, `api/agent_routes.py`, `frontend/src/components/RefreshButton.jsx` | integration |

---

### Task 1: Schema — `apply_url` / `apply_kind` on jobs

**Files:**
- Modify: `src/job_dashboard/models.py` (JobListing), `src/job_dashboard/db.py` (`init_db`, `insert_job`, `query_jobs`, `job_detail`)
- Test: `tests/test_db_apply_columns.py`

**Interfaces:**
- Produces: `JobListing.apply_url: Optional[str] = None`, `JobListing.apply_kind: Optional[str] = None` (`native|external|unknown`); `jobs.apply_url`, `jobs.apply_kind` columns; index `jobs_source_ext(source, external_id)`; `query_jobs`/`job_detail` dicts include `apply_url`, `apply_kind`.

- [ ] **Step 1: Failing test**

```python
# tests/test_db_apply_columns.py
from job_dashboard.db import init_db, insert_job, job_detail, query_jobs
from job_dashboard.models import JobListing


def _job(**kw):
    base = dict(source="linkedin", title="ML Engineer", company="Acme", job_url="https://www.linkedin.com/jobs/view/1",
                description="d", external_id="1")
    return JobListing(**{**base, **kw})


def test_apply_fields_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    assert insert_job(conn, _job(apply_url="https://acme.com/apply", apply_kind="external"))
    jobs, _ = query_jobs(conn)
    assert jobs[0]["apply_url"] == "https://acme.com/apply" and jobs[0]["apply_kind"] == "external"
    d = job_detail(conn, jobs[0]["id"])
    assert d["apply_url"] == "https://acme.com/apply" and d["apply_kind"] == "external"


def test_migration_is_idempotent_and_indexed(tmp_path):
    p = str(tmp_path / "j.db")
    init_db(p).close()
    conn = init_db(p)
    names = [r[1] for r in conn.execute("PRAGMA index_list(jobs)")]
    assert "jobs_source_ext" in names
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]
    assert cols.count("apply_url") == 1
    jobs, _ = query_jobs(conn)
    assert jobs == []
```

- [ ] **Step 2:** Run `PYTHONPATH=src python3 -m pytest tests/test_db_apply_columns.py -q` → FAIL (`unexpected keyword 'apply_url'`).

- [ ] **Step 3: Implement**

`models.py` — append to `JobListing` after `posted_date`:
```python
    apply_url: Optional[str] = None
    apply_kind: Optional[str] = None   # native | external | unknown
```
`db.py` — add after `_ensure_expired_column`, and call `_ensure_apply_columns(conn)` in `init_db` right after `_ensure_expired_column(conn)`:
```python
def _ensure_apply_columns(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    for c in ("apply_url", "apply_kind"):
        if c not in cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {c} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_source_ext ON jobs(source, external_id)")
```
`insert_job` — INSERT column list gains `apply_url, apply_kind` (14 placeholders) and values `job.apply_url, job.apply_kind` after `job.posted_date` and before the `fetched_at` value (keep column/value order identical: `..., salary_text, posted_date, apply_url, apply_kind, fetched_at`).
`query_jobs` — SELECT gains `, j.apply_url, j.apply_kind` after `cc.company_type`; the zip tuple becomes `_JOB_COLUMNS + ("industry", "company_type", "apply_url", "apply_kind")`.
`job_detail` — SELECT gains `, j.apply_url, j.apply_kind` after `m.flags`; zip tuple `... "gaps", "flags", "apply_url", "apply_kind")`.

- [ ] **Step 4:** Run the new test plus `PYTHONPATH=src python3 -m pytest tests/test_db.py tests/test_api.py tests/test_pipeline.py -q` → all PASS.
- [ ] **Step 5: Commit**
```bash
git add tests/test_db_apply_columns.py src/job_dashboard/models.py src/job_dashboard/db.py
git commit -m "feat(jobs): apply_url/apply_kind columns and source+external_id index"
```
(If `git diff` shows other sessions' hunks in `db.py`, stage only yours with `git add -p`.)

---

### Task 2: Types + `CdpSession`

**Files:**
- Create: `src/job_dashboard/sources/cdp/__init__.py` (empty), `types.py`, `session.py`, `tests/cdp_fakes.py`
- Test: `tests/test_cdp_session.py`

**Interfaces:**
- Produces: `Blocked`, `CapReached` exceptions; `AdapterContext(mode, known, terms, max_pages, stop_after_known, stats)`; `SiteResult(site, mode, new, skipped_known, pages, note).as_dict()`; `cdp_reachable(cdp_url) -> bool`; `CdpSession(cdp_url, *, max_loads, nap=None, connect=None, settle_ms=7000)` as context manager with `.goto(url)` (raises `Blocked` on 403/429/login-ish URL/challenge text, `CapReached` past `max_loads`; naps before every load except the first), `.capture(*needles)` → `Capture` context manager with `.bodies()` yielding `(url, json)`; `.loads`.
- Test helpers: `FakePage(script, text, status)`, `make_session(page, **kw)` (nap disabled, `connect` faked).

This code was prototyped and its tests passed (8 passed) before the plan was written; copy it verbatim.

- [ ] **Step 1: Write tests + fakes** (files below are exactly what to create)

`tests/cdp_fakes.py`:
```python
class FakeResponse:
    def __init__(self, url, body, status=200):
        self.url, self._body, self.status = url, body, status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakePage:
    """script: {url_or_prefix*: [(response_url, body), ...]} fired on goto."""

    def __init__(self, script=None, text="", status=200):
        self.script, self.text, self.status = script or {}, text, status
        self.url, self.visited, self.handlers, self.closed = "", [], [], False

    def on(self, event, fn):
        assert event == "response"
        self.handlers.append(fn)

    def remove_listener(self, event, fn):
        self.handlers.remove(fn)

    def goto(self, url, wait_until=None):
        self.url = url
        self.visited.append(url)
        for key, resps in self.script.items():
            if key == url or (key.endswith("*") and url.startswith(key[:-1])):
                for ru, body in resps:
                    for h in list(self.handlers):
                        h(FakeResponse(ru, body))
        return FakeResponse(url, None, self.status)

    def evaluate(self, js):
        return self.text

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        self.closed = True


def make_session(page, **kw):
    from job_dashboard.sources.cdp.session import CdpSession
    closed = []
    s = CdpSession("http://x", max_loads=kw.pop("max_loads", 50), nap=lambda: None,
                   connect=lambda url: (page, lambda: closed.append(1)), **kw)
    s.closed = closed
    return s
```

`tests/test_cdp_session.py`:
```python
import pytest
from job_dashboard.sources.cdp.types import Blocked, CapReached
from tests.cdp_fakes import FakePage, make_session


def test_captures_only_matching_responses_and_skips_bad_json():
    page = FakePage({"https://a/": [("https://x/voyagerJobsDashJobCards?q", {"n": 1}),
                                     ("https://x/other", {"n": 2}),
                                     ("https://x/voyagerJobsDashJobCards?bad", ValueError("no json"))]})
    with make_session(page) as s:
        with s.capture("voyagerJobsDashJobCards") as cap:
            s.goto("https://a/")
    assert [b for _, b in cap.bodies()] == [{"n": 1}]
    assert page.handlers == []          # listener removed on exit


def test_closes_only_own_tab_and_detaches():
    page = FakePage()
    s = make_session(page)
    with s:
        pass
    assert page.closed and s.closed == [1]


def test_cap_reached_after_max_loads():
    with make_session(FakePage(), max_loads=2) as s:
        s.goto("https://a/1"); s.goto("https://a/2")
        with pytest.raises(CapReached):
            s.goto("https://a/3")


@pytest.mark.parametrize("kw", [
    dict(status=403), dict(status=429), dict(text="We noticed unusual activity from your account"),
])
def test_blocked_signals(kw):
    with make_session(FakePage(**kw)) as s:
        with pytest.raises(Blocked):
            s.goto("https://a/")


def test_blocked_on_login_redirect():
    with make_session(FakePage()) as s:
        with pytest.raises(Blocked):
            s.goto("https://www.linkedin.com/authwall?trk=x")


def test_naps_between_loads_but_not_before_the_first():
    from job_dashboard.sources.cdp.session import CdpSession
    naps, page = [], FakePage()
    with CdpSession("u", max_loads=9, nap=lambda: naps.append(1),
                    connect=lambda u: (page, lambda: None)) as s:
        s.goto("https://a/1"); s.goto("https://a/2"); s.goto("https://a/3")
    assert naps == [1, 1]
```

- [ ] **Step 2:** Run → FAIL (`ModuleNotFoundError: job_dashboard.sources.cdp`). Note `tests/` needs `tests/__init__.py`; it exists if other tests import `tests.` — if not, `touch tests/__init__.py` and check `pytest` still collects (or use `from cdp_fakes import ...` with `conftest`-relative import; pick whichever the suite already does).

- [ ] **Step 3: Implement**

`src/job_dashboard/sources/cdp/types.py`:
```python
"""Shared types for browser (CDP) job sources."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable


class Blocked(Exception):
    """The site challenged or blocked us (login wall, captcha, 403/429...). Never retried."""


class CapReached(Exception):
    """Per-run page-load cap hit. Not an error: known jobs are skipped next time, so the
    next run continues where this one stopped."""


@dataclass
class AdapterContext:
    mode: str                                  # "backfill" | "incremental"
    known: Callable[[str, str], bool]          # (external_id, canonical_url) -> already in the DB
    terms: list
    max_pages: int
    stop_after_known: int
    stats: dict = field(default_factory=lambda: {"skipped_known": 0, "pages": 0})


@dataclass
class SiteResult:
    site: str
    mode: str = ""
    new: int = 0
    skipped_known: int = 0
    pages: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)
```

`src/job_dashboard/sources/cdp/session.py`:
```python
"""The only module that touches Playwright. One own tab per run, no click / type / form API:
an adapter can navigate and listen to the responses the page itself makes, nothing else."""
from __future__ import annotations

import random
import re
import time
import urllib.request

from .types import Blocked, CapReached

BAD_URL = re.compile(r"authwall|/login|/checkpoint|/uas/|challenge|captcha", re.I)
BAD_TEXT = re.compile(
    r"unusual activity|verify you.re a human|security verification|"
    r"let.s do a quick security check|temporarily restricted", re.I)


def cdp_reachable(cdp_url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def _playwright_connect(cdp_url: str):
    """(page, closer). closer detaches Playwright; it does not close Chrome or other tabs."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url)
    page = browser.contexts[0].new_page()

    def closer():
        try:
            browser.close()
        finally:
            pw.stop()
    return page, closer


class Capture:
    """Collects the page's own responses whose URL contains any needle."""

    def __init__(self, page, needles):
        self._page, self._needles, self.responses = page, needles, []

    def _on(self, response):
        if any(n in response.url for n in self._needles):
            self.responses.append(response)

    def __enter__(self):
        self._page.on("response", self._on)
        return self

    def __exit__(self, *exc):
        self._page.remove_listener("response", self._on)

    def bodies(self):
        """(url, parsed json) for each captured response that parses."""
        for r in self.responses:
            try:
                yield r.url, r.json()
            except Exception:
                continue


class CdpSession:
    def __init__(self, cdp_url, *, max_loads, nap=None, connect=None, settle_ms=7000):
        self.cdp_url, self.max_loads, self.loads = cdp_url, max_loads, 0
        self._nap = nap or (lambda: time.sleep(random.uniform(6, 12)))
        self._connect = connect or _playwright_connect
        self._settle_ms = settle_ms
        self._page = self._closer = None

    def __enter__(self):
        self._page, self._closer = self._connect(self.cdp_url)
        return self

    def __exit__(self, *exc):
        for fn in (lambda: self._page.close(), lambda: self._closer()):
            try:
                fn()
            except Exception:
                pass

    def capture(self, *needles) -> Capture:
        return Capture(self._page, needles)

    def goto(self, url: str) -> None:
        if self.loads >= self.max_loads:
            raise CapReached(f"{self.max_loads} page loads")
        if self.loads:
            self._nap()
        self.loads += 1
        resp = self._page.goto(url, wait_until="domcontentloaded")
        self._check(getattr(resp, "status", None))
        self._page.wait_for_timeout(self._settle_ms)
        self._check(None)

    def _check(self, status):
        if status in (403, 429) or BAD_URL.search(self._page.url or ""):
            raise Blocked(f"{self._page.url} status={status}")
        text = self._page.evaluate("document.body ? document.body.innerText.slice(0, 3000) : ''")
        if BAD_TEXT.search(text or ""):
            raise Blocked("challenge text on page")
```

- [ ] **Step 4:** Run `PYTHONPATH=src python3 -m pytest tests/test_cdp_session.py -q` → `8 passed` (6 test functions, 3 parametrized cases → 8).
- [ ] **Step 5: Commit**
```bash
git add src/job_dashboard/sources/cdp tests/cdp_fakes.py tests/test_cdp_session.py
git commit -m "feat(cdp): CdpSession - navigate + listen only, pacing, caps, block detection"
```

---

### Task 3: `fetch_state`, cadence gate, settings

**Files:**
- Create: `src/job_dashboard/sources/cdp/state.py`
- Modify: `src/job_dashboard/qa_store.py` (`DEFAULT_SETTINGS`)
- Test: `tests/test_cdp_state.py`

**Interfaces:**
- Consumes: `qa_store.get_setting(conn, key)`, `qa_store.set_setting(conn, key, value)`.
- Produces: `ensure(conn)`; `enabled(conn, site) -> bool`; `interval_hours(conn) -> float`; `get(conn, site) -> dict|None`; `due(conn, site, now=None) -> bool` (True if never succeeded or `last_success_at` older than the interval); `mode_for(conn, site) -> "backfill"|"incremental"`; `record_run(conn, site, *, ok, new=0, skipped=0, error=None, backfill_done=None, now=None)`; `DEFAULT_SETTINGS` gains `"browser_min_interval_hours": "48"`, `"browser_linkedin_enabled": "0"`.

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_state.py
import sqlite3
from datetime import datetime, timedelta, timezone
from job_dashboard import qa_store
from job_dashboard.sources.cdp import state

T0 = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)


def conn():
    c = sqlite3.connect(":memory:")
    state.ensure(c)
    return c


def test_disabled_by_default_and_toggle():
    c = conn()
    assert state.enabled(c, "linkedin") is False
    qa_store.set_setting(c, "browser_linkedin_enabled", "1")
    assert state.enabled(c, "linkedin") is True


def test_first_run_is_due_and_backfill():
    c = conn()
    assert state.due(c, "linkedin", now=T0) and state.mode_for(c, "linkedin") == "backfill"


def test_due_respects_48h_after_success():
    c = conn()
    state.record_run(c, "linkedin", ok=True, new=5, backfill_done=True, now=T0)
    assert not state.due(c, "linkedin", now=T0 + timedelta(hours=47))
    assert state.due(c, "linkedin", now=T0 + timedelta(hours=49))
    assert state.mode_for(c, "linkedin") == "incremental"


def test_failed_run_keeps_last_success_and_records_error():
    c = conn()
    state.record_run(c, "linkedin", ok=True, backfill_done=True, now=T0)
    state.record_run(c, "linkedin", ok=False, error="Blocked: authwall", now=T0 + timedelta(hours=60))
    row = state.get(c, "linkedin")
    assert row["last_error"] == "Blocked: authwall" and row["last_success_at"] == T0.isoformat()
    assert state.due(c, "linkedin", now=T0 + timedelta(hours=61))


def test_failed_first_run_stays_backfill():
    c = conn()
    state.record_run(c, "linkedin", ok=False, error="x", now=T0)
    assert state.mode_for(c, "linkedin") == "backfill"
```

- [ ] **Step 2:** Run → FAIL (module missing).

- [ ] **Step 3: Implement**

`qa_store.py`: `DEFAULT_SETTINGS = {"answer_confidence_min": "60", "browser_min_interval_hours": "48", "browser_linkedin_enabled": "0"}`.

`state.py`:
```python
"""Per-site fetch bookkeeping: when a site last ran, whether its backfill finished, last error."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_dashboard import qa_store


def ensure(conn) -> None:
    qa_store.ensure(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS fetch_state (
        site TEXT PRIMARY KEY, last_run_at TEXT, last_success_at TEXT,
        backfill_done INTEGER NOT NULL DEFAULT 0, last_new INTEGER, last_skipped INTEGER,
        last_error TEXT, anchor TEXT)""")
    conn.commit()


def enabled(conn, site: str) -> bool:
    return qa_store.get_setting(conn, f"browser_{site}_enabled") == "1"


def interval_hours(conn) -> float:
    try:
        return float(qa_store.get_setting(conn, "browser_min_interval_hours"))
    except (TypeError, ValueError):
        return 48.0


def get(conn, site: str):
    ensure(conn)
    cur = conn.execute("SELECT * FROM fetch_state WHERE site=?", (site,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def due(conn, site: str, now=None) -> bool:
    row = get(conn, site)
    if not row or not row["last_success_at"]:
        return True
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(row["last_success_at"]) >= timedelta(hours=interval_hours(conn))


def mode_for(conn, site: str) -> str:
    row = get(conn, site)
    return "incremental" if row and row["backfill_done"] else "backfill"


def record_run(conn, site, *, ok, new=0, skipped=0, error=None, backfill_done=None, now=None):
    ensure(conn)
    now = (now or datetime.now(timezone.utc)).isoformat()
    prev = get(conn, site) or {}
    conn.execute(
        """INSERT INTO fetch_state (site, last_run_at, last_success_at, backfill_done,
                                    last_new, last_skipped, last_error)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(site) DO UPDATE SET last_run_at=excluded.last_run_at,
             last_success_at=excluded.last_success_at, backfill_done=excluded.backfill_done,
             last_new=excluded.last_new, last_skipped=excluded.last_skipped, last_error=excluded.last_error""",
        (site, now, now if ok else prev.get("last_success_at"),
         int(bool(backfill_done)) if backfill_done is not None else int(prev.get("backfill_done") or 0),
         new, skipped, error))
    conn.commit()
```

- [ ] **Step 4:** Run → 5 PASS. Also `tests/test_qa_store.py` (if present) still passes.
- [ ] **Step 5: Commit**
```bash
git add src/job_dashboard/sources/cdp/state.py src/job_dashboard/qa_store.py tests/test_cdp_state.py
git commit -m "feat(cdp): fetch_state table, 48h cadence gate, per-site enable setting"
```

---

### Task 4: LinkedIn parsing (pure functions)

**Files:**
- Create: `src/job_dashboard/sources/cdp/linkedin.py` (parsing half)
- Test: `tests/test_cdp_linkedin_parse.py`

**Interfaces:**
- Produces: `SITE = "linkedin"`; `search_url(term, hours, start=0, location="India") -> str`; `parse_cards(body) -> (dict id->card, total|None)`; `parse_details(body) -> dict id->detail`; `apply_kind(card, detail) -> "native"|"external"`; `to_listing(card, detail) -> JobListing`; `job_url(id) -> str`.
- Card dict keys: `id,title,company,location,salary,listed_ms,easy_apply_card,reposted`. Detail keys: `description,posted_on,onsite_apply,ats,apply_url,apply_cta,created_ms`.

Fixtures are synthetic voyager JSON mirroring exactly the fields the verified sketch (`docs/career-agent/job-source-research/linkedin_fetch_sketch.py`) reads; Task 10 validates them against the live payload.

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_linkedin_parse.py
from job_dashboard.sources.cdp import linkedin as li

CARDS = {"data": {"paging": {"total": 1093}}, "included": [
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:111",
     "jobPostingTitle": "ML Engineer", "primaryDescription": {"text": "Acme"},
     "secondaryDescription": {"text": "Bengaluru, India"}, "tertiaryDescription": {"text": "₹20L"},
     "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000000000}, {"type": "EASY_APPLY_TEXT"}]},
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:222",
     "jobPostingTitle": "Data Scientist", "primaryDescription": {"text": "Beta"},
     "secondaryDescription": {"text": "Remote"}, "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000005000}]},
    {"$type": "com.linkedin.voyager.dash.jobs.JobPostingCard", "jobPostingUrn": "urn:li:fsd_jobPosting:333"},  # no title
    {"$type": "com.linkedin.voyager.dash.jobs.JobPosting", "entityUrn": "urn:li:fsd_jobPosting:222", "repostedJob": True},
]}
DETAILS = {"included": [
    {"$type": "x.JobDescription", "entityUrn": "urn:li:fsd_jobPosting:111", "descriptionText": {"text": "Build models"},
     "postedOnText": "2 days ago"},
    {"$type": "x.JobSeekerApplicationDetail", "entityUrn": "urn:li:fsd_jobPosting:111", "onsiteApply": True},
    {"$type": "x.JobDescription", "entityUrn": "urn:li:fsd_jobPosting:222", "descriptionText": {"text": "Analyse"}},
    {"$type": "x.JobSeekerApplicationDetail", "entityUrn": "urn:li:fsd_jobPosting:222", "onsiteApply": False,
     "applicantTrackingSystemName": "Greenhouse", "companyApplyUrl": "https://boards.greenhouse.io/beta/1"},
]}


def test_parse_cards():
    cards, total = li.parse_cards(CARDS)
    assert total == 1093 and set(cards) == {"111", "222"}
    assert cards["111"]["easy_apply_card"] and cards["111"]["listed_ms"] == 1790000000000
    assert cards["222"]["reposted"] is True and not cards["222"]["easy_apply_card"]


def test_parse_details_and_apply_kind():
    d = li.parse_details(DETAILS)
    assert d["111"]["description"] == "Build models" and d["222"]["apply_url"].startswith("https://boards")
    cards, _ = li.parse_cards(CARDS)
    assert li.apply_kind(cards["111"], d["111"]) == "native"
    assert li.apply_kind(cards["222"], d["222"]) == "external"
    assert li.apply_kind(cards["111"], {}) == "native"          # falls back to card flag


def test_to_listing():
    cards, _ = li.parse_cards(CARDS); d = li.parse_details(DETAILS)
    j = li.to_listing(cards["222"], d["222"])
    assert (j.source, j.external_id, j.job_url) == ("linkedin", "222", "https://www.linkedin.com/jobs/view/222")
    assert j.apply_kind == "external" and j.apply_url.startswith("https://boards") and j.description == "Analyse"
    assert j.posted_date.startswith("2026-")


def test_search_url_window_and_paging():
    u = li.search_url("data scientist", 48, start=25)
    assert "keywords=data%20scientist" in u and "f_TPR=r172800" in u and "sortBy=DD" in u and "start=25" in u
    assert "start=" not in li.search_url("x", 24)
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Implement** `linkedin.py` (this task's half; Task 5 appends `run`):

```python
"""LinkedIn Jobs adapter. Reads only the responses LinkedIn's own SPA makes when a search page
loads (voyagerJobsDashJobCards + the jobPostingDetailDescription prefetch); no clicks.
Extraction logic verified in docs/career-agent/job-source-research/linkedin_fetch_sketch.py."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from job_dashboard.models import JobListing

SITE = "linkedin"
BASE = "https://www.linkedin.com/jobs/search/"
# 48h verified working (1,093 results vs 900 for 24h, 1,428 for 7d). Max 30 days (retention rule).
TPR = {24: "r86400", 48: "r172800", 168: "r604800", 720: "r2592000"}


def job_url(jid: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{jid}"


def search_url(term, hours=None, start=0, location="India", sort="DD") -> str:
    u = f"{BASE}?keywords={quote(term)}&location={quote(location)}"
    if sort:
        u += f"&sortBy={sort}"
    if hours:
        u += f"&f_TPR={TPR[hours]}"
    if start:
        u += f"&start={start}"
    return u


def _t(x):
    return (x or {}).get("text")


def parse_cards(body):
    inc = body.get("included", [])
    posting = {x["entityUrn"].rsplit(":", 1)[-1]: x for x in inc
               if x.get("$type", "").endswith(".JobPosting") and x.get("entityUrn")}
    out = {}
    for x in inc:
        urn = x.get("jobPostingUrn") or x.get("*jobPosting")
        if not x.get("$type", "").endswith("JobPostingCard") or not x.get("jobPostingTitle") or not urn:
            continue
        jid = urn.rsplit(":", 1)[-1]
        ft = {i["type"]: i for i in x.get("footerItems") or []}
        out[jid] = dict(
            id=jid, title=x["jobPostingTitle"], company=_t(x.get("primaryDescription")),
            location=_t(x.get("secondaryDescription")), salary=_t(x.get("tertiaryDescription")),
            listed_ms=(ft.get("LISTED_DATE") or {}).get("timeAt"),
            easy_apply_card="EASY_APPLY_TEXT" in ft,
            reposted=(posting.get(jid) or {}).get("repostedJob"))
    total = ((body.get("data") or {}).get("paging") or {}).get("total")
    return out, total


def parse_details(body):
    out = {}

    def slot(x):
        return out.setdefault(x["entityUrn"].rsplit(":", 1)[-1], {})
    for x in body.get("included", []):
        t = x.get("$type", "")
        if not x.get("entityUrn"):
            continue
        if t.endswith(".JobDescription"):
            s = slot(x); s["description"] = _t(x.get("descriptionText")); s["posted_on"] = x.get("postedOnText")
        elif t.endswith(".JobSeekerApplicationDetail"):
            slot(x).update(onsite_apply=x.get("onsiteApply"), ats=x.get("applicantTrackingSystemName"),
                           apply_url=x.get("companyApplyUrl"), apply_cta=_t(x.get("applyCtaText")))
        elif t.endswith(".JobPosting") and x.get("createdAt"):
            slot(x)["created_ms"] = x["createdAt"]
    return out


def apply_kind(card, detail) -> str:
    """native = Easy Apply, external = employer/ATS. Card flag matched onsiteApply in 82/82 checked."""
    if detail.get("onsite_apply") is not None:
        return "native" if detail["onsite_apply"] else "external"
    return "native" if card.get("easy_apply_card") else "external"


def to_listing(card, detail) -> JobListing:
    ms = card.get("listed_ms") or detail.get("created_ms")
    posted = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None
    return JobListing(
        source=SITE, external_id=card["id"], title=card["title"], company=card.get("company") or "",
        location=card.get("location"), job_url=job_url(card["id"]),
        description=detail.get("description") or "", salary_text=card.get("salary"), posted_date=posted,
        apply_url=detail.get("apply_url"), apply_kind=apply_kind(card, detail))
```

- [ ] **Step 4:** Run → 4 PASS.
- [ ] **Step 5: Commit**
```bash
git add src/job_dashboard/sources/cdp/linkedin.py tests/test_cdp_linkedin_parse.py
git commit -m "feat(cdp): LinkedIn card/detail parsing and JobListing mapping"
```

---

### Task 5: LinkedIn adapter `run(session, ctx)`

**Files:**
- Modify: `src/job_dashboard/sources/cdp/linkedin.py` (append)
- Test: `tests/test_cdp_linkedin_run.py`

**Interfaces:**
- Consumes: `CdpSession.goto/capture`, `AdapterContext`, Task 4 functions, `Blocked`, `CapReached`.
- Produces: `TERMS` (7 terms from spec); `run(session, ctx) -> list[JobListing]`. Behaviour: for each term, for each page `p < ctx.max_pages`, load `search_url(term, 48 if incremental else 720, start=25*p)`; a page load returns cards (two calls, ~50) and details for the first ~24. For each card: `ctx.known(id, url)` → count `skipped_known`, `consecutive_known += 1`; else if description present in details → listing; else **detail load** `session.goto(job_url(id))`, capture `jobPostingDetailDescription`, `parse_details`; no description captured → skip this run, do NOT treat as known (retry next run). Any new job resets `consecutive_known`. Incremental: when `consecutive_known >= ctx.stop_after_known` end the term. Stop the term when a page has no cards. `Blocked` propagates. `CapReached` ends the whole run, returning what was collected. `ctx.stats["pages"]` counts search pages. Duplicate ids across terms collapse (first wins).

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_linkedin_run.py
import pytest
from job_dashboard.sources.cdp import linkedin as li
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, make_session

CARD_URL = "https://x/voyager/api/voyagerJobsDashJobCards?q=1"
DET_URL = "https://x/voyager/api/graphql?queryId=jobPostingDetailDescription"


def card(i, easy=False):
    return {"$type": "a.JobPostingCard", "jobPostingUrn": f"urn:li:fsd_jobPosting:{i}", "jobPostingTitle": f"T{i}",
            "primaryDescription": {"text": "Co"}, "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000000000}]
            + ([{"type": "EASY_APPLY_TEXT"}] if easy else [])}


def det(i, text="desc"):
    return {"$type": "a.JobDescription", "entityUrn": f"urn:li:fsd_jobPosting:{i}", "descriptionText": {"text": text}}


def ctx(known=(), **kw):
    base = dict(mode="incremental", known=lambda i, u: i in known, terms=["ml"], max_pages=2, stop_after_known=3)
    return AdapterContext(**{**base, **kw})


def page_for(term_pages, details=(), view=None):
    script = {}
    for url, ids in term_pages.items():
        script[url] = [(CARD_URL, {"included": [card(i) for i in ids]}), (DET_URL, {"included": [det(i) for i in details]})]
    for i, body in (view or {}).items():
        script[li.job_url(i)] = [(DET_URL, {"included": body})]
    return FakePage(script)


def test_new_jobs_use_prefetched_description_and_skip_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1", "2"], li.search_url("ml", 48, start=25): []}, details=["1", "2"])
    c = ctx(known={"2"})
    with make_session(page) as s:
        out = li.run(s, c)
    assert [j.external_id for j in out] == ["1"] and c.stats["skipped_known"] == 1
    assert page.visited == [u0, li.search_url("ml", 48, start=25)]      # no detail loads


def test_stops_term_after_n_consecutive_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1", "2", "3", "4"]}, details=[])
    c = ctx(known={"1", "2", "3", "4"}, stop_after_known=3)
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert page.visited == [u0]                                           # page 2 never loaded


def test_card_without_prefetch_gets_detail_load():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=25): []}, details=[],
                    view={"9": [det("9", "from view page")]})
    with make_session(page) as s:
        out = li.run(s, ctx())
    assert out[0].description == "from view page" and li.job_url("9") in page.visited


def test_card_with_no_description_anywhere_is_skipped_not_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=25): []}, details=[])
    c = ctx()
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert c.stats["skipped_known"] == 0


def test_backfill_uses_30_day_window_and_no_early_stop():
    u = li.search_url("ml", 720)
    page = page_for({u: ["1", "2", "3", "4"], li.search_url("ml", 720, start=25): []}, details=["1"])
    c = ctx(mode="backfill", known={"1", "2", "3", "4"}, stop_after_known=3)
    with make_session(page) as s:
        li.run(s, c)
    assert len(page.visited) == 2


def test_blocked_propagates_and_cap_returns_partial():
    with make_session(FakePage(status=429)) as s:
        with pytest.raises(Blocked):
            li.run(s, ctx())
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1"]}, details=["1"])
    with make_session(page, max_loads=1) as s:
        assert [j.external_id for j in li.run(s, ctx())] == ["1"]         # cap hit on page 2, keeps page 1


def test_same_job_from_two_terms_collapses():
    pages = {li.search_url(t, 48): ["1"] for t in ("a", "b")}
    pages.update({li.search_url(t, 48, start=25): [] for t in ("a", "b")})
    with make_session(page_for(pages, details=["1"])) as s:
        assert len(li.run(s, ctx(terms=["a", "b"]))) == 1
```

- [ ] **Step 2:** Run → FAIL (`no attribute 'run'`).

- [ ] **Step 3: Implement** — append to `linkedin.py`:

```python
from .types import CapReached  # noqa: E402  (bottom import keeps the parsing half dependency-free)

# Spec terms (docs/career-agent/2026-09-25-cdp-job-fetching-design.md, LinkedIn section).
TERMS = ["machine learning engineer", "ai engineer", "data scientist", "llm engineer",
         "mlops engineer", "senior data scientist", "risk data scientist"]
_NEEDLES = ("voyagerJobsDashJobCards", "jobPostingDetailDescription")


def _load(session, url):
    """One page load -> (cards, details) from the responses LinkedIn's SPA made itself."""
    cards, details = {}, {}
    with session.capture(*_NEEDLES) as cap:
        session.goto(url)
    for u, body in cap.bodies():
        if "voyagerJobsDashJobCards" in u:
            cards.update(parse_cards(body)[0])
        else:
            details.update(parse_details(body))
    return cards, details


def run(session, ctx):
    hours = 720 if ctx.mode == "backfill" else 48
    found = {}
    try:
        for term in ctx.terms:
            consecutive_known = 0
            for p in range(ctx.max_pages):
                cards, details = _load(session, search_url(term, hours, start=25 * p))
                ctx.stats["pages"] += 1
                if not cards:
                    break
                for jid, c in cards.items():
                    if jid in found:
                        continue
                    if ctx.known(jid, job_url(jid)):
                        ctx.stats["skipped_known"] += 1
                        consecutive_known += 1
                        continue
                    d = details.get(jid) or {}
                    if not d.get("description"):
                        d = _load(session, job_url(jid))[1].get(jid) or {}
                    if not d.get("description"):
                        continue                        # retried next run; deliberately not "known"
                    found[jid] = to_listing(c, d)
                    consecutive_known = 0
                if ctx.mode == "incremental" and consecutive_known >= ctx.stop_after_known:
                    break
    except CapReached:
        pass
    return list(found.values())
```

Also set the module docstring's imports properly: move `from .types import CapReached` to the top import block when implementing (the bottom import above is only to keep Task 4 self-contained).

- [ ] **Step 4:** Run → 7 PASS. Fix by reading failures, not by loosening assertions.
- [ ] **Step 5: Commit**
```bash
git add src/job_dashboard/sources/cdp/linkedin.py tests/test_cdp_linkedin_run.py
git commit -m "feat(cdp): LinkedIn adapter - skip-known, stop after N known, detail fallback"
```

---

### Task 6: Runner

**Files:**
- Create: `src/job_dashboard/sources/cdp/runner.py`
- Test: `tests/test_cdp_runner.py`

**Interfaces:**
- Consumes: `state.*`, `cdp_reachable`, `CdpSession`, `linkedin.run/TERMS/SITE`, `job_exists`.
- Produces: `ADAPTERS = {"linkedin": (linkedin.run, linkedin.TERMS)}`; `fetch_browser_sources(conn, *, adapters=ADAPTERS, cdp_url="http://localhost:9222", session_factory=None, reachable=cdp_reachable, now=None) -> (listings, list[SiteResult])`. `session_factory(max_loads) -> CdpSession`. Per enabled+due site: pick mode, build `AdapterContext` (incremental: max_pages 3, stop_after_known 10, cap 30; backfill: max_pages 2 ×7 terms... use `max_pages=2`, cap 60, `stop_after_known=10**9`), run in try/except, `record_run`. Not enabled → no result at all. Enabled but not due → `SiteResult(note="not due")`. CDP unreachable → `SiteResult(note="Chrome CDP not reachable")` and no state change. `Blocked` → note `"blocked: …"`, `record_run(ok=False)`. Other exception → note `"error: …"`, `record_run(ok=False)`. Success → `record_run(ok=True, backfill_done=True, new=len, skipped=…)`. A failing site never prevents the others.

- [ ] **Step 1: Failing test**

```python
# tests/test_cdp_runner.py
import sqlite3
from job_dashboard import qa_store
from job_dashboard.models import JobListing
from job_dashboard.sources.cdp import runner, state
from job_dashboard.sources.cdp.types import Blocked
from tests.cdp_fakes import FakePage, make_session


def conn(enabled=True):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source TEXT, external_id TEXT, job_url TEXT)")
    state.ensure(c)
    if enabled:
        qa_store.set_setting(c, "browser_linkedin_enabled", "1")
    return c


def L(i):
    return JobListing(source="linkedin", title="t", company="c", job_url=f"u{i}", description="d", external_id=str(i))


def go(c, run, **kw):
    adapters = {"linkedin": (run, ["t"])}
    return runner.fetch_browser_sources(
        c, adapters=adapters, reachable=lambda u: True,
        session_factory=lambda cap: make_session(FakePage(), max_loads=cap), **kw)


def test_disabled_site_is_silent():
    listings, results = go(conn(enabled=False), lambda s, ctx: [L(1)])
    assert listings == [] and results == []


def test_success_records_state_and_flips_to_incremental():
    c = conn(); seen = []
    def run(s, ctx):
        seen.append(ctx.mode); ctx.stats["skipped_known"] = 4; return [L(1), L(2)]
    listings, results = go(c, run)
    assert len(listings) == 2 and results[0].new == 2 and results[0].skipped_known == 4
    assert seen == ["backfill"] and state.mode_for(c, "linkedin") == "incremental"


def test_second_run_within_48h_is_not_due():
    c = conn(); go(c, lambda s, ctx: [])
    _, results = go(c, lambda s, ctx: [L(1)])
    assert results[0].note == "not due" and results[0].new == 0


def test_blocked_is_recorded_and_isolated():
    c = conn()
    def boom(s, ctx): raise Blocked("authwall")
    listings, results = go(c, boom)
    assert listings == [] and results[0].note.startswith("blocked")
    assert state.get(c, "linkedin")["last_error"].startswith("Blocked")
    assert state.mode_for(c, "linkedin") == "backfill"


def test_known_callback_checks_external_id_and_url():
    c = conn(); c.execute("INSERT INTO jobs (source, external_id, job_url) VALUES ('linkedin','7','u7')"); c.commit()
    got = {}
    def run(s, ctx): got["a"] = ctx.known("7", "x"); got["b"] = ctx.known("8", "u7"); got["c"] = ctx.known("8", "x"); return []
    go(c, run)
    assert got == {"a": True, "b": True, "c": False}


def test_cdp_down_changes_nothing():
    c = conn()
    _, results = runner.fetch_browser_sources(c, adapters={"linkedin": (lambda s, x: [], ["t"])},
                                              reachable=lambda u: False, session_factory=None)
    assert results[0].note == "Chrome CDP not reachable" and state.get(c, "linkedin") is None
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement**

```python
"""Runs each enabled, due browser adapter in isolation and records its state."""
from __future__ import annotations

from job_dashboard.sources.cdp import linkedin, state
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext, Blocked, SiteResult

ADAPTERS = {linkedin.SITE: (linkedin.run, linkedin.TERMS)}
CDP_URL = "http://localhost:9222"
# mode -> (max search pages per term, page-load cap, stop after N consecutive known)
LIMITS = {"incremental": (3, 30, 10), "backfill": (2, 60, 10**9)}


def fetch_browser_sources(conn, *, adapters=ADAPTERS, cdp_url=CDP_URL, session_factory=None,
                          reachable=cdp_reachable, now=None):
    listings, results = [], []
    for site, (run, terms) in adapters.items():
        if not state.enabled(conn, site):
            continue
        if not state.due(conn, site, now=now):
            results.append(SiteResult(site, note="not due"))
            continue
        if not reachable(cdp_url):
            results.append(SiteResult(site, note="Chrome CDP not reachable"))
            continue
        mode = state.mode_for(conn, site)
        pages, cap, stop_known = LIMITS[mode]
        known = _known_fn(conn, site)
        ctx = AdapterContext(mode=mode, known=known, terms=terms, max_pages=pages, stop_after_known=stop_known)
        res = SiteResult(site, mode=mode)
        try:
            factory = session_factory or (lambda c: CdpSession(cdp_url, max_loads=c))
            with factory(cap) as session:
                found = run(session, ctx)
            res.new, res.skipped_known, res.pages = len(found), ctx.stats["skipped_known"], ctx.stats["pages"]
            listings.extend(found)
            state.record_run(conn, site, ok=True, new=res.new, skipped=res.skipped_known,
                             backfill_done=True, now=now)
        except Blocked as exc:
            res.note = f"blocked: {exc}"
            state.record_run(conn, site, ok=False, error=f"Blocked: {exc}", now=now)
        except Exception as exc:                       # one site must never break Refresh
            res.note = f"error: {exc}"
            state.record_run(conn, site, ok=False, error=f"{type(exc).__name__}: {exc}", now=now)
        results.append(res)
    return listings, results


def _known_fn(conn, site):
    def known(external_id, url):
        return conn.execute(
            "SELECT 1 FROM jobs WHERE (source=? AND external_id=?) OR job_url=? LIMIT 1",
            (site, external_id, url)).fetchone() is not None
    return known
```

- [ ] **Step 4:** Run → 6 PASS. **Step 5: Commit**
```bash
git add src/job_dashboard/sources/cdp/runner.py tests/test_cdp_runner.py
git commit -m "feat(cdp): runner - per-site isolation, cadence, modes, state recording"
```

---

### Task 7: Pipeline + Refresh integration and enable switch

**Files:**
- Modify: `src/job_dashboard/pipeline.py`, `src/job_dashboard/api/refresh_job.py`, `src/job_dashboard/api/qa_routes.py` (`SettingsBody`, `get_settings`, `put_settings`)
- Test: `tests/test_pipeline_browser.py`, extend `tests/test_api.py` or a new `tests/test_cdp_settings_api.py`

**Interfaces:**
- Consumes: `fetch_browser_sources(conn) -> (listings, [SiteResult])`, `insert_job`.
- Produces: `run_pipeline(..., browser_fetch=None)`; when given, stage `"browser sources"` runs after ingest and before dedupe: `listings, results = browser_fetch(conn)`; each listing goes through `insert_job` (returns bool); result dict gains `"browser": [SiteResult.as_dict() with new = actually-inserted count]`. `browser_fetch` exceptions are swallowed into `"browser": [{"site":"browser","note":"error: …"}]` — never abort ingest. `_summarize` appends `"linkedin +12"` / `"linkedin: not due"` style parts. `default_pipeline_runner` passes `browser_fetch=fetch_browser_sources`. Settings API: `GET /api/agent-settings` also returns `browser_linkedin_enabled` (bool) and `browser_min_interval_hours`; `PUT` accepts optional `browser_linkedin_enabled: bool`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_pipeline_browser.py
from job_dashboard.db import init_db
from job_dashboard.models import JobListing
from job_dashboard.pipeline import run_pipeline
from job_dashboard.api.refresh_job import _summarize
from job_dashboard.sources.cdp.types import SiteResult


def L(i):
    return JobListing(source="linkedin", title=f"t{i}", company="c", job_url=f"https://l/{i}",
                      description="d", external_id=str(i), apply_kind="native")


def _run(conn, bf):
    return run_pipeline(conn, [], [], browser_fetch=bf,
                        model_loader=lambda: (_ for _ in ()).throw(RuntimeError("no model")))


def test_browser_listings_are_inserted_and_counted(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    r = _run(conn, lambda c: ([L(1), L(2)], [SiteResult("linkedin", mode="backfill", new=2)]))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    assert r["browser"][0]["site"] == "linkedin" and r["browser"][0]["new"] == 2


def test_duplicate_url_not_counted_as_new(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    _run(conn, lambda c: ([L(1)], [SiteResult("linkedin", new=1)]))
    r = _run(conn, lambda c: ([L(1)], [SiteResult("linkedin", new=1)]))
    assert r["browser"][0]["new"] == 0


def test_browser_failure_never_aborts_pipeline(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    def boom(c): raise RuntimeError("chrome exploded")
    r = _run(conn, boom)
    assert "chrome exploded" in r["browser"][0]["note"] and "ingest" in r


def test_no_browser_fetch_means_no_key_change_needed(tmp_path):
    conn = init_db(str(tmp_path / "j.db"))
    assert _run(conn, None)["browser"] == []


def test_summarize_lists_each_site():
    s = _summarize({"ingest": {"new_jobs": 3}, "embed_scored": 3,
                    "browser": [{"site": "linkedin", "new": 12, "note": ""}, {"site": "naukri", "new": 0, "note": "not due"}]})
    assert "linkedin +12" in s and "naukri: not due" in s
```

```python
# tests/test_cdp_settings_api.py
from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app


def test_enable_switch_roundtrip(tmp_path):
    c = TestClient(create_app(str(tmp_path / "j.db"), pipeline_runner=lambda p, s: {}))
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is False
    assert c.put("/api/agent-settings", json={"browser_linkedin_enabled": True}).status_code == 200
    assert c.get("/api/agent-settings").json()["browser_linkedin_enabled"] is True
```

- [ ] **Step 2:** Run → FAIL. First view `qa_routes.py` lines ~230-260 (`SettingsBody`, `get_settings`, `put_settings`) and extend in the same style; keep `answer_confidence_min` behaviour and its existing tests unchanged (make it `Optional` only if the model currently requires it — check).

- [ ] **Step 3: Implement**
`pipeline.py` — signature gains `browser_fetch=None`; after `ingest_result = ...` add:
```python
    browser = []
    if browser_fetch is not None:
        _stage("browser sources")
        try:
            listings, site_results = browser_fetch(conn)
            by_site = {r.site: r for r in site_results}
            inserted = {}
            for job in listings:
                if insert_job(conn, job):
                    inserted[job.source] = inserted.get(job.source, 0) + 1
            for r in site_results:
                r.new = inserted.get(r.site, 0)
            browser = [r.as_dict() for r in by_site.values()]
        except Exception as exc:
            browser = [{"site": "browser", "new": 0, "note": f"error: {exc}"}]
```
Result dict adds `"browser": browser`. Import `insert_job` from `job_dashboard.db`.
`refresh_job.py` — `_summarize`: after the embed part:
```python
    for b in result.get("browser") or []:
        parts.append(f"{b['site']}: {b['note']}" if b.get("note") else f"{b['site']} +{b.get('new', 0)}")
```
and `default_pipeline_runner` passes `browser_fetch=fetch_browser_sources` (import from `job_dashboard.sources.cdp.runner`).
`qa_routes.py` — `SettingsBody.browser_linkedin_enabled: Optional[bool] = None`; in `put_settings` `if body.browser_linkedin_enabled is not None: qa_store.set_setting(conn, "browser_linkedin_enabled", "1" if body.browser_linkedin_enabled else "0")`; `get_settings` adds `"browser_linkedin_enabled": get_setting(...) == "1"` and `"browser_min_interval_hours": float(...)`.

- [ ] **Step 4:** Run the two new files plus `tests/test_pipeline.py tests/test_pipeline_stages.py tests/test_api.py tests/test_qa_api.py -q` → PASS (note: other sessions modified `tests/test_pipeline*.py`; if they fail for unrelated reasons, report, don't fix).
- [ ] **Step 5: Commit** (only your hunks)
```bash
git add tests/test_pipeline_browser.py tests/test_cdp_settings_api.py src/job_dashboard/pipeline.py src/job_dashboard/api/refresh_job.py src/job_dashboard/api/qa_routes.py
git commit -m "feat(refresh): browser-sources stage, per-site summary, enable switch"
```

---

### Task 8: RefreshButton per-site lines

**Files:** Modify `frontend/src/components/RefreshButton.jsx`; test in the existing frontend test file for RefreshButton (find with `ls frontend/src/**/*Refresh*`; if none exists, add `frontend/src/components/RefreshButton.test.jsx` in the style of a neighbouring `*.test.jsx`).

- [ ] **Step 1: Failing test** — render with `refreshStatus` mocked to `{running:false, stage:"done", last_result:{browser:[{site:"linkedin",new:12,note:""},{site:"naukri",new:0,note:"blocked: authwall"}]}}`; expect text `linkedin +12` and `naukri: blocked: authwall` present (role `status`), and that a blocked note has `role="alert"`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run RefreshButton` → FAIL.
- [ ] **Step 3: Implement** — after the `embed_skipped` block add:
```jsx
      {(status.last_result?.browser || []).map((b) => (
        <span key={b.site} role={b.note?.startsWith("blocked") || b.note?.startsWith("error") ? "alert" : "status"}
          style={{ fontSize: 11, background: "var(--warm-tint)", color: "var(--warm-ink)", borderRadius: 8, padding: "3px 8px" }}>
          {b.note ? `${b.site}: ${b.note}` : `${b.site} +${b.new}`}
        </span>
      ))}
```
- [ ] **Step 4:** Test PASS; `cd frontend && npm run build` succeeds. **Step 5: Commit** `git add frontend/src/components/RefreshButton.jsx <test file>`; message `feat(ui): per-site browser fetch result in Refresh button`.

---

### Task 9: `apply_kind` / `apply_url` drive the badge and the agent

**Files:**
- Modify: `src/job_dashboard/match/apply_type.py`, `src/job_dashboard/api/app.py` (two call sites), `src/job_dashboard/api/agent_routes.py` (~line 225 and ~289)
- Test: extend `tests/test_apply_type.py`; add cases to `tests/test_agent_api.py`

**Interfaces:** `classify_apply_type(source, job_url, apply_kind=None, apply_url=None)`. Precedence: `apply_kind=="native"` → `{"kind":"easy-apply","label":"Easy Apply","fill":"manual"}` (agent cannot drive LinkedIn's shadow-DOM Easy Apply — see memory `career-agent-linkedin-findings`); `apply_kind=="external"` with `apply_url` → classify by the `apply_url` (existing heuristic, which yields ATS/company-site → `easy`), falling back to `{"kind":"external","label":"Company site","fill":"maybe"}`; otherwise the existing behaviour, unchanged. Agent `--url`: `apply_url` if `apply_kind == "external"` and present, else `job_url`.

- [ ] **Step 1: Failing tests**
```python
def test_native_easy_apply_is_manual():
    r = classify_apply_type("linkedin", "https://www.linkedin.com/jobs/view/1", apply_kind="native")
    assert r["kind"] == "easy-apply" and r["fill"] == "manual"

def test_external_uses_apply_url_host():
    r = classify_apply_type("linkedin", "https://www.linkedin.com/jobs/view/1", "external", "https://boards.greenhouse.io/x/1")
    assert r["kind"] == "external-ats" and r["fill"] == "easy"

def test_null_apply_kind_falls_back_to_old_heuristic():
    assert classify_apply_type("linkedin", "https://www.linkedin.com/jobs/view/1")["kind"] == "linkedin"
```
plus an agent-route test in `tests/test_agent_api.py` (style of its existing launch test, which stubs the subprocess): a job inserted with `apply_kind="external", apply_url="https://boards.greenhouse.io/x/1"` launches with that URL after `--url`; a job without it launches with `job_url`.
- [ ] **Step 2:** FAIL. **Step 3: Implement** the precedence above; in `app.py` pass `j.get("apply_kind"), j.get("apply_url")` at both call sites; in `agent_routes.py` compute `target = detail["apply_url"] if detail.get("apply_kind") == "external" and detail.get("apply_url") else detail.get("job_url")`, use it for the 422 check and `--url` (leave the thread-id hash on `job_url`, ~line 289, untouched so run history keeps matching).
- [ ] **Step 4:** `pytest tests/test_apply_type.py tests/test_agent_api.py tests/test_api.py -q` PASS. **Step 5: Commit** `feat(apply): prefer apply_kind/apply_url for badge and agent target`.

---

### Task 10: Gated live smoke (validates the synthetic fixtures)

**Files:** Create `tests/test_cdp_live_linkedin.py`

- [ ] **Step 1: Write** (skipped unless `RUN_CDP_TESTS=1`; needs the career-agent Chrome on :9222, logged in to LinkedIn):
```python
import os
import pytest
from job_dashboard.sources.cdp import linkedin as li
from job_dashboard.sources.cdp.session import CdpSession, cdp_reachable
from job_dashboard.sources.cdp.types import AdapterContext

pytestmark = pytest.mark.skipif(os.environ.get("RUN_CDP_TESTS") != "1" or not cdp_reachable("http://localhost:9222"),
                                reason="needs RUN_CDP_TESTS=1 and Chrome on :9222")


def test_one_search_page_parses_and_view_page_fires_detail():
    ctx = AdapterContext("incremental", lambda i, u: False, ["machine learning engineer"], max_pages=1, stop_after_known=10)
    with CdpSession("http://localhost:9222", max_loads=6) as s:
        jobs = li.run(s, ctx)
    assert jobs and all(j.title and j.description and j.job_url.startswith("https://www.linkedin.com/jobs/view/") for j in jobs)
    assert {j.apply_kind for j in jobs} <= {"native", "external"}
    print(len(jobs), "jobs;", sum(bool(j.apply_url) for j in jobs), "with apply_url; loads:", s.loads)
```
- [ ] **Step 2:** `RUN_CDP_TESTS=1 PYTHONPATH=src python3 -m pytest tests/test_cdp_live_linkedin.py -q -s`. Expected: PASS with ~24+ jobs. **If it fails:** the failure message is the finding — likely the `/jobs/view/<id>` page does not fire `jobPostingDetailDescription` (spec-flagged unknown) or a field name differs. Record the real shape in the spec's LinkedIn section, adjust `parse_*`/fixtures in Tasks 4–5 to the real payload, re-run. Do not enable `browser_linkedin_enabled` until this passes.
- [ ] **Step 3: Commit** `test(cdp): gated live LinkedIn smoke check`.

---

## After the plan: day-2 gate (not code)

1. Run Task 10 smoke, then `PUT /api/agent-settings {"browser_linkedin_enabled": true}`, Refresh once (backfill, ≤ 60 loads).
2. Next day: Refresh again (incremental). Compare against `data/research_baselines/linkedin_2026-09-25.json`: expect known jobs skipped, only day-2 jobs inserted. If confirmed, the day-2 check is done; leave the switch on.

## Self-review

- **Spec coverage:** CdpSession (T2), fetch_state + 48h gate + settings (T3), LinkedIn extraction/terms/windows/stop-after-known/reposts-same-id (T4–5), runner isolation + caps + modes (T6), pipeline stage + summary (T7), UI (T8), apply_url/apply_kind + index (T1, T9), retention window ≤30d (T4 `TPR`, T5 backfill 720h), enable-off default (T3). Deferred by design: recurring 30-day prune, `click_pagination`, Naukri/Wellfound/Instahyre/IIMJobs adapters, hiring-signal extraction.
- **Placeholder scan:** none; T8/T9 give test intent and the exact implementation code but reference existing test files by style — the implementer must read the neighbour test first.
- **Type consistency:** `AdapterContext(mode, known, terms, max_pages, stop_after_known, stats)` matches T5/T6/T10; `SiteResult.as_dict()` keys `site,mode,new,skipped_known,pages,note` match T7 `_summarize`/UI; `fetch_browser_sources(conn, ...)` returns `(listings, results)` matching T7's `browser_fetch(conn)`; `state.record_run` kwargs consistent T3/T6.
