# Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web dashboard (FastAPI JSON API + React/Vite SPA) over the existing SQLite job database: browsable scored feed, filters, job detail, status tracking, suspected-duplicates section, and a one-click background pipeline refresh — in the light-pastel playful register with first-class micro-animations.

**Architecture:** `src/job_dashboard/api/` (FastAPI app + background refresh job) reads/writes only through new `db.py` functions. `src/job_dashboard/sources.py` registers the six real fetchers for `run_pipeline`, which gains an optional `on_stage` callback. `frontend/` is an isolated Vite+React app; dev uses the Vite proxy, daily use serves `frontend/dist` from FastAPI.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, sqlite3 (stdlib), pytest + httpx (TestClient); Node 18+, React 18, Vite 5, Vitest + React Testing Library.

## Global Constraints

- Scores are **filters, never gates** — no listing is removed or hidden by default; `min_score` filters only when the user sets it; dismissed jobs are excluded by default but restorable via `include_dismissed=true` and a visible UI toggle.
- Suspected duplicates are **marked, never deleted**; the UI has no delete action for them.
- `db.py` is the only module that touches SQL.
- Job status values: `saved`, `applied`, `dismissed`, or `NULL` (= new). Anything else is a 422/ValueError.
- Refresh: `POST /api/refresh` returns 409 if a run is in progress; embedding problems surface as non-fatal `embed_skipped` (warning banner), never as a failed refresh.
- No test performs a real network call, requires sentence-transformers, or hits a real browser.
- Visual register (binding, from the spec): pastel families — lavender `#EEEDFE/#3C3489`, mint `#E1F5EE/#085041`, peach/amber `#FAEEDA/#633806`, pink `#FBEAF0/#72243E`; text on a pastel fill always uses the dark end of the same family; pill shapes for small tags/chips/buttons only.
- Design discipline (binding, from the `minimalist-ui` taste skill — `.agents/skills/minimalist-ui/SKILL.md`):
  - Fonts: sans stack `'SF Pro Display', 'Helvetica Neue', system-ui, sans-serif` (never Inter/Roboto/Open Sans); metadata (dates, source names, scores' sublabels) in monospace `'SF Mono', 'JetBrains Mono', monospace`, small size, wide tracking.
  - Text: body never pure black — warm charcoal `#2C2C2A`; secondary `#787774`; line-height ≥1.6 on prose (the JD text).
  - Structure: card radius 12px max; hairline borders `1px` at ~6% opacity; generous internal padding; canvas warm bone `#F7F6F3`.
  - No emoji or unicode symbol glyphs in markup (⟳ ✕ ✓ ▾ etc.) — use small inline SVG primitives with consistent stroke width.
  - No gradients, no heavy shadows (any shadow ≤ 0.05 opacity), no glassmorphism.
  - **Documented deviation (user preference governs):** the skill treats color as scarce and bans colored backgrounds on large elements; the user explicitly chose a pastel playful register, so the lavender header band and pastel strengths/gaps cards stay. Pastel stays desaturated (the chosen 50-stop fills), never saturated primaries.
- Motion (binding — skill physics + spec behaviors): staggered row entrance `translateY(12px)+fade`, 600ms, `cubic-bezier(0.16,1,0.3,1)`, 80ms/row cascade; verdict-pill pop-in; hover = 200ms ultra-subtle shadow lift (`0 2px 8px rgba(0,0,0,0.04)`) + gentle nudge; `scale(0.98)` on button press; score count-up (<1s); refresh spin; breathing live-dot. Animate only `transform`/`opacity`. All disabled under `prefers-reduced-motion: reduce`.
- Frontend code lives only in `frontend/`; `frontend/dist/` and `node_modules/` are gitignored.

---

## File Structure

```
src/job_dashboard/
  db.py                    # MODIFIED: status column + query/detail/stats functions
  pipeline.py              # MODIFIED: optional on_stage callback
  sources.py               # NEW: registry of the six real fetchers
  api/
    __init__.py            # NEW (empty)
    app.py                 # NEW: create_app() with all endpoints + static serving
    refresh_job.py         # NEW: RefreshState + background thread runner
frontend/
  package.json, vite.config.js, index.html
  src/main.jsx, src/App.jsx, src/api.js
  src/styles/tokens.css, src/styles/app.css
  src/components/{FilterBar,Feed,ScoreBadge,JobDetail,DuplicatesSection,RefreshButton}.jsx
  src/__tests__/{feed.test.jsx, detail.test.jsx}
tests/
  test_db_dashboard.py     # NEW
  test_sources.py          # NEW
  test_pipeline_stages.py  # NEW
  test_api.py              # NEW
  test_refresh_api.py      # NEW
requirements.txt           # MODIFIED: + fastapi, uvicorn, httpx
.gitignore                 # MODIFIED: + node_modules/, frontend/dist/
```

---

### Task 1: DB extensions — status column + dashboard query functions

**Files:**
- Modify: `src/job_dashboard/db.py`
- Test: `tests/test_db_dashboard.py`

**Interfaces:**
- Consumes: existing `init_db`, `insert_job`, `upsert_embed_score`, `record_llm_evaluation`, `mark_duplicate`.
- Produces (in `job_dashboard.db`, used by Tasks 3–4):
  - `VALID_STATUSES = {"saved", "applied", "dismissed"}`
  - `set_job_status(conn, job_id: int, status: str | None) -> None` — ValueError on bad status, KeyError on unknown id
  - `query_jobs(conn, q=None, remote=None, job_type=None, source=None, status=None, min_score=None, include_dismissed=False, sort="embed", limit=50, offset=0) -> (list[dict], int)` — canonical rows LEFT JOINed with scores; dict keys: id, title, company, location, job_url, job_type, is_remote, posted_date, source, status, embed_score, llm_score, verdict
  - `job_detail(conn, job_id: int) -> dict | None` — adds description, strengths/gaps/flags (parsed JSON, default []/[]/{}), cross_listings
  - `dashboard_stats(conn) -> dict` — keys: total, new, saved, applied, dismissed, unranked

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_dashboard.py
import pytest

from job_dashboard.db import (
    dashboard_stats, init_db, insert_job, job_detail, mark_duplicate,
    query_jobs, record_llm_evaluation, set_job_status, upsert_embed_score,
)
from job_dashboard.models import JobListing


def _seed(conn, n, **overrides):
    fields = dict(
        source=f"src{n}", title=f"Role {n}", company=f"Co {n}",
        job_url=f"https://x.com/{n}", description=f"desc {n}",
    )
    fields.update(overrides)
    insert_job(conn, JobListing(**fields))
    return conn.execute("SELECT id FROM jobs ORDER BY id DESC").fetchone()[0]


def test_set_job_status_validates_and_updates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    jid = _seed(conn, 1)

    set_job_status(conn, jid, "saved")
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "saved"
    set_job_status(conn, jid, None)  # clear back to new
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] is None

    with pytest.raises(ValueError):
        set_job_status(conn, jid, "bogus")
    with pytest.raises(KeyError):
        set_job_status(conn, 99999, "saved")


def test_query_jobs_excludes_dismissed_by_default_but_never_deletes(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    set_job_status(conn, b, "dismissed")

    rows, total = query_jobs(conn)
    assert [r["id"] for r in rows] == [a] and total == 1

    rows, total = query_jobs(conn, include_dismissed=True)
    assert total == 2

    rows, _ = query_jobs(conn, status="dismissed")
    assert [r["id"] for r in rows] == [b]


def test_query_jobs_sorts_by_embed_score_and_min_score_is_opt_in(tmp_path):
    conn = init_db(tmp_path / "t.db")
    lo = _seed(conn, 1)
    hi = _seed(conn, 2)
    unscored = _seed(conn, 3)
    upsert_embed_score(conn, lo, 0.3, "h")
    upsert_embed_score(conn, hi, 0.9, "h")

    rows, total = query_jobs(conn, sort="embed")
    assert total == 3  # unscored still present — scores never gate
    assert [r["id"] for r in rows] == [hi, lo, unscored]

    rows, total = query_jobs(conn, min_score=0.5)
    assert [r["id"] for r in rows] == [hi]


def test_query_jobs_text_search_and_filters(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed(conn, 1, title="ML Engineer", company="Stripe", is_remote=True)
    _seed(conn, 2, title="Chef", company="Bistro", is_remote=False)

    rows, _ = query_jobs(conn, q="stripe")
    assert len(rows) == 1 and rows[0]["company"] == "Stripe"
    rows, _ = query_jobs(conn, remote=True)
    assert len(rows) == 1 and rows[0]["title"] == "ML Engineer"


def test_query_jobs_skips_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    mark_duplicate(conn, b, a)

    rows, total = query_jobs(conn)
    assert total == 1 and rows[0]["id"] == a


def test_job_detail_includes_scores_lists_and_cross_listings(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2, source="remoteok")
    mark_duplicate(conn, b, a)
    upsert_embed_score(conn, a, 0.8, "h")
    record_llm_evaluation(conn, a, 87, "Strong Fit", ["prod ML"], ["k8s"], {"expired": False})

    detail = job_detail(conn, a)
    assert detail["description"] == "desc 1"
    assert detail["llm_score"] == 87
    assert detail["strengths"] == ["prod ML"]
    assert detail["flags"] == {"expired": False}
    assert detail["cross_listings"][0]["source"] == "remoteok"

    assert job_detail(conn, 99999) is None


def test_job_detail_defaults_empty_lists_when_unranked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    detail = job_detail(conn, a)
    assert detail["strengths"] == [] and detail["gaps"] == [] and detail["flags"] == {}


def test_dashboard_stats(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = _seed(conn, 1)
    b = _seed(conn, 2)
    c = _seed(conn, 3)
    set_job_status(conn, b, "applied")
    upsert_embed_score(conn, a, 0.8, "h")
    record_llm_evaluation(conn, a, 80, "Good Fit", [], [], {})

    stats = dashboard_stats(conn)
    assert stats == {"total": 3, "new": 2, "saved": 0, "applied": 1,
                     "dismissed": 0, "unranked": 2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db_dashboard.py -v`
Expected: FAIL with `ImportError` (new names missing)

- [ ] **Step 3: Implement in `db.py`**

Add `_ensure_status_column` beside `_ensure_duplicate_of_column` and call it from `init_db`:

```python
def _ensure_status_column(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if "status" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT")
```

Append (module-level `VALID_STATUSES = {"saved", "applied", "dismissed"}`):

```python
def set_job_status(conn, job_id, status):
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)} or None, got {status!r}")
    cur = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    if cur.rowcount == 0:
        raise KeyError(f"no job with id {job_id}")


_JOB_COLUMNS = ("id", "title", "company", "location", "job_url", "job_type",
                "is_remote", "posted_date", "source", "status",
                "embed_score", "llm_score", "verdict")


def query_jobs(conn, q=None, remote=None, job_type=None, source=None, status=None,
               min_score=None, include_dismissed=False, sort="embed",
               limit=50, offset=0):
    where = ["j.duplicate_of IS NULL"]
    params = []
    if q:
        where.append("(LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)")
        needle = f"%{q.lower()}%"
        params += [needle, needle]
    if remote is not None:
        where.append("j.is_remote = ?")
        params.append(int(remote))
    if job_type:
        where.append("j.job_type = ?")
        params.append(job_type)
    if source:
        where.append("j.source = ?")
        params.append(source)
    if status:
        where.append("j.status = ?")
        params.append(status)
    elif not include_dismissed:
        where.append("(j.status IS NULL OR j.status != 'dismissed')")
    if min_score is not None:
        where.append("m.embed_score >= ?")
        params.append(min_score)

    order = {
        "embed": "m.embed_score IS NULL, m.embed_score DESC, j.id",
        "llm": "m.llm_score IS NULL, m.llm_score DESC, j.id",
        "date": "j.posted_date IS NULL, j.posted_date DESC, j.id",
    }.get(sort, "m.embed_score IS NULL, m.embed_score DESC, j.id")

    base = f"""FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
               WHERE {' AND '.join(where)}"""
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_type,
                   j.is_remote, j.posted_date, j.source, j.status,
                   m.embed_score, m.llm_score, m.verdict
            {base} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return [dict(zip(_JOB_COLUMNS, row)) for row in rows], total


def job_detail(conn, job_id):
    row = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_type,
                  j.is_remote, j.posted_date, j.source, j.status,
                  m.embed_score, m.llm_score, m.verdict,
                  j.description, m.strengths, m.gaps, m.flags
           FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
           WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    detail = dict(zip(_JOB_COLUMNS + ("description", "strengths", "gaps", "flags"), row))
    detail["strengths"] = json.loads(detail["strengths"]) if detail["strengths"] else []
    detail["gaps"] = json.loads(detail["gaps"]) if detail["gaps"] else []
    detail["flags"] = json.loads(detail["flags"]) if detail["flags"] else {}
    detail["cross_listings"] = [
        {"id": r[0], "source": r[1], "job_url": r[2]}
        for r in conn.execute(
            "SELECT id, source, job_url FROM jobs WHERE duplicate_of = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    ]
    return detail


def dashboard_stats(conn):
    def one(sql, *params):
        return conn.execute(sql, params).fetchone()[0]

    canonical = "FROM jobs WHERE duplicate_of IS NULL"
    return {
        "total": one(f"SELECT COUNT(*) {canonical}"),
        "new": one(f"SELECT COUNT(*) {canonical} AND status IS NULL"),
        "saved": one(f"SELECT COUNT(*) {canonical} AND status = 'saved'"),
        "applied": one(f"SELECT COUNT(*) {canonical} AND status = 'applied'"),
        "dismissed": one(f"SELECT COUNT(*) {canonical} AND status = 'dismissed'"),
        "unranked": one(
            """SELECT COUNT(*) FROM jobs j LEFT JOIN match_scores m ON m.job_id = j.id
               WHERE j.duplicate_of IS NULL AND m.llm_score IS NULL"""
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db_dashboard.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Full suite**

Run: `python3 -m pytest`
Expected: 57 passed (49 existing + 8 new)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/db.py tests/test_db_dashboard.py
git commit -m "feat: job status column and dashboard query functions in db.py"
```

---

### Task 2: `sources.py` registry + `on_stage` pipeline callback

**Files:**
- Create: `src/job_dashboard/sources.py`
- Modify: `src/job_dashboard/pipeline.py`
- Test: `tests/test_sources.py`, `tests/test_pipeline_stages.py`

**Interfaces:**
- Produces: `job_sources() -> list[callable]`, `company_sources() -> list[callable]` (no-arg callables for `run_pipeline`); `SEARCH_TERMS: list[str]` module constant.
- Produces: `run_pipeline(..., on_stage=None)` — invokes `on_stage("ingesting")`, `on_stage("deduping")`, `on_stage("scoring")` at stage starts; existing callers unaffected.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sources.py
from job_dashboard import sources


def test_job_sources_returns_noarg_callables_without_network(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "fetch_jobspy_jobs", lambda *a, **k: calls.append("jobspy") or [])
    monkeypatch.setattr(sources, "fetch_remotive_jobs", lambda *a, **k: calls.append("remotive") or [])
    monkeypatch.setattr(sources, "fetch_remoteok_jobs", lambda *a, **k: calls.append("remoteok") or [])
    monkeypatch.setattr(sources, "fetch_wwr_jobs", lambda *a, **k: calls.append("wwr") or [])
    monkeypatch.setattr(sources, "fetch_himalayas_jobs", lambda *a, **k: calls.append("himalayas") or [])

    fetchers = sources.job_sources()
    assert len(fetchers) >= 5
    for fetch in fetchers:
        assert fetch() == []
    assert {"jobspy", "remotive", "remoteok", "wwr", "himalayas"} <= set(calls)


def test_company_sources_wraps_startup_sheet(monkeypatch):
    monkeypatch.setattr(sources, "fetch_funded_startups", lambda: ["co"])
    fetchers = sources.company_sources()
    assert len(fetchers) == 1
    assert fetchers[0]() == ["co"]
```

```python
# tests/test_pipeline_stages.py
from job_dashboard import pipeline
from job_dashboard.db import init_db
from job_dashboard.models import JobListing


class FakeModel:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_run_pipeline_reports_stages_in_order(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text("# P\n- ml\n")
    job = JobListing(source="a", title="T", company="C",
                     job_url="https://x.com/1", description="d")
    stages = []

    pipeline.run_pipeline(
        conn, job_sources=[lambda: [job]], company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(), on_stage=stages.append,
    )

    assert stages == ["ingesting", "deduping", "scoring"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sources.py tests/test_pipeline_stages.py -v`
Expected: FAIL (`No module named 'job_dashboard.sources'` is a package dir — the new module is `sources.py` at package root, distinct from the `sources/` subpackage: **name it `source_registry.py` instead** to avoid shadowing. Adjust: the module is `src/job_dashboard/source_registry.py` and tests import `from job_dashboard import source_registry as sources`.)

> **Naming resolution (binding):** the existing `job_dashboard/sources/` package makes a sibling `sources.py` impossible. The registry module is `src/job_dashboard/source_registry.py`. Both test files import it as `from job_dashboard import source_registry as sources`. The spec's `sources.py` name maps to this file.

- [ ] **Step 3: Implement `source_registry.py`**

```python
# src/job_dashboard/source_registry.py
"""Registry wiring the real fetchers into run_pipeline.

Adding a source later = one entry here. Query terms are kept broad across the
profile's target titles (see search-queries.md) — remote-first, not overfit.
"""
from job_dashboard.sources.himalayas_source import fetch_himalayas_jobs
from job_dashboard.sources.jobspy_source import fetch_jobspy_jobs
from job_dashboard.sources.remoteok_source import fetch_remoteok_jobs
from job_dashboard.sources.remotive_source import fetch_remotive_jobs
from job_dashboard.sources.startup_sheet import fetch_funded_startups
from job_dashboard.sources.wwr_source import fetch_wwr_jobs

SEARCH_TERMS = ["machine learning engineer", "ai engineer", "senior data scientist"]


def job_sources():
    fetchers = []
    for term in SEARCH_TERMS:
        fetchers.append(lambda t=term: fetch_jobspy_jobs(t, "Remote", ["linkedin", "indeed"]))
        fetchers.append(lambda t=term: fetch_remotive_jobs(t))
        fetchers.append(lambda t=term: fetch_himalayas_jobs(t))
    fetchers.append(lambda: fetch_remoteok_jobs())
    fetchers.append(lambda: fetch_wwr_jobs())
    return fetchers


def company_sources():
    return [lambda: fetch_funded_startups()]
```

(The monkeypatched names in the test target this module's globals — import the fetchers as module attributes exactly as above so `monkeypatch.setattr(sources, "fetch_jobspy_jobs", ...)` works.)

- [ ] **Step 4: Add `on_stage` to `run_pipeline`**

In `pipeline.py`, change the signature to `def run_pipeline(conn, job_sources, company_sources, profile_file=None, evaluation_file=None, model_loader=load_default_model, on_stage=None):` and add a helper at the top of the body:

```python
    def _stage(name):
        if on_stage is not None:
            on_stage(name)
```

Call `_stage("ingesting")` immediately before `run_ingest`, `_stage("deduping")` before `mark_duplicates`, and `_stage("scoring")` at the start of the embed-stage `try` block. No other behavior changes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sources.py tests/test_pipeline_stages.py tests/test_pipeline.py -v`
Expected: PASS (2 + 1 + 4 existing pipeline tests)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/source_registry.py src/job_dashboard/pipeline.py tests/test_sources.py tests/test_pipeline_stages.py
git commit -m "feat: source registry for real fetchers and on_stage pipeline callback"
```

---

### Task 3: FastAPI app — jobs/detail/status/duplicates/stats endpoints

**Files:**
- Create: `src/job_dashboard/api/__init__.py` (empty), `src/job_dashboard/api/app.py`
- Modify: `requirements.txt` (add `fastapi>=0.110`, `uvicorn>=0.29`, `httpx>=0.27`)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1's db functions + `suspected_duplicates` (existing).
- Produces: `create_app(db_path) -> FastAPI` serving `GET /api/jobs`, `GET /api/jobs/{id}`, `PATCH /api/jobs/{id}/status`, `GET /api/duplicates`, `GET /api/stats`. (Refresh endpoints come in Task 4; static serving in Task 8.)

- [ ] **Step 1: Install backend deps**

```bash
pip3 install "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27"
```
Append the three lines to `requirements.txt`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_api.py
import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import (
    init_db, insert_job, mark_duplicate, record_llm_evaluation, upsert_embed_score,
)
from job_dashboard.models import JobListing


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    for n, (title, company) in enumerate(
        [("ML Engineer", "Stripe"), ("Chef", "Bistro"), ("AI Engineer", "Acme")], 1
    ):
        insert_job(conn, JobListing(source="s", title=title, company=company,
                                    job_url=f"https://x.com/{n}", description=f"jd {n}"))
    ids = [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]
    upsert_embed_score(conn, ids[0], 0.9, "h")
    record_llm_evaluation(conn, ids[0], 87, "Strong Fit", ["prod ML"], ["k8s"], {})
    mark_duplicate(conn, ids[2], ids[0])
    conn.close()
    app = create_app(db_path=str(db_path))
    return TestClient(app), ids


def test_get_jobs_returns_canonical_scored_feed(client):
    tc, ids = client
    resp = tc.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2  # duplicate excluded
    assert body["jobs"][0]["id"] == ids[0]
    assert body["jobs"][0]["llm_score"] == 87


def test_get_jobs_filters_pass_through(client):
    tc, _ = client
    assert tc.get("/api/jobs", params={"q": "stripe"}).json()["total"] == 1
    assert tc.get("/api/jobs", params={"min_score": 0.5}).json()["total"] == 1


def test_job_detail_and_404(client):
    tc, ids = client
    body = tc.get(f"/api/jobs/{ids[0]}").json()
    assert body["description"] == "jd 1"
    assert body["strengths"] == ["prod ML"]
    assert body["cross_listings"][0]["id"] == ids[2]
    assert tc.get("/api/jobs/999999").status_code == 404


def test_patch_status_validates(client):
    tc, ids = client
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": "saved"}).status_code == 200
    assert tc.get(f"/api/jobs/{ids[1]}").json()["status"] == "saved"
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": None}).status_code == 200
    assert tc.patch(f"/api/jobs/{ids[1]}/status", json={"status": "bogus"}).status_code == 422
    assert tc.patch("/api/jobs/999999/status", json={"status": "saved"}).status_code == 404


def test_duplicates_and_stats(client):
    tc, ids = client
    dupes = tc.get("/api/duplicates").json()["duplicates"]
    assert len(dupes) == 1 and dupes[0]["duplicate_of"] == ids[0]

    stats = tc.get("/api/stats").json()
    assert stats["total"] == 2 and stats["unranked"] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.api'`

- [ ] **Step 4: Implement `api/app.py`**

```python
# src/job_dashboard/api/app.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from job_dashboard.db import (
    dashboard_stats, init_db, job_detail, query_jobs, set_job_status,
    suspected_duplicates,
)

DEFAULT_DB = "data/jobs.db"


class StatusPatch(BaseModel):
    status: Optional[str] = None


def create_app(db_path=DEFAULT_DB):
    app = FastAPI(title="Job Dashboard")

    @contextmanager
    def db():
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/jobs")
    def list_jobs(q: str = None, remote: bool = None, job_type: str = None,
                  source: str = None, status: str = None, min_score: float = None,
                  include_dismissed: bool = False, sort: str = "embed",
                  limit: int = 50, offset: int = 0):
        with db() as conn:
            jobs, total = query_jobs(
                conn, q=q, remote=remote, job_type=job_type, source=source,
                status=status, min_score=min_score,
                include_dismissed=include_dismissed, sort=sort,
                limit=limit, offset=offset,
            )
        return {"jobs": jobs, "total": total}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        with db() as conn:
            detail = job_detail(conn, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return detail

    @app.patch("/api/jobs/{job_id}/status")
    def patch_status(job_id: int, body: StatusPatch):
        with db() as conn:
            try:
                set_job_status(conn, job_id, body.status)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except KeyError:
                raise HTTPException(status_code=404, detail="job not found")
        return {"ok": True, "status": body.status}

    @app.get("/api/duplicates")
    def list_duplicates():
        with db() as conn:
            return {"duplicates": suspected_duplicates(conn)}

    @app.get("/api/stats")
    def stats():
        with db() as conn:
            return dashboard_stats(conn)

    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Full suite + commit**

Run: `python3 -m pytest` → all pass.

```bash
git add src/job_dashboard/api/__init__.py src/job_dashboard/api/app.py tests/test_api.py requirements.txt
git commit -m "feat: FastAPI dashboard API — jobs, detail, status, duplicates, stats"
```

---

### Task 4: Background refresh job + endpoints

**Files:**
- Create: `src/job_dashboard/api/refresh_job.py`
- Modify: `src/job_dashboard/api/app.py`
- Test: `tests/test_refresh_api.py`

**Interfaces:**
- Produces: `RefreshState` class — `.snapshot() -> dict` (`{running, stage, detail, last_result, error}`), `.start(runner) -> bool` (False if already running; `runner(on_stage) -> dict` executes in a daemon thread).
- Produces in `create_app(db_path, pipeline_runner=None)`: `POST /api/refresh` (200 `{"started": true}` / 409), `GET /api/refresh/status`. `pipeline_runner(db_path, on_stage) -> dict` is injectable for tests; the default runs `run_pipeline` with `source_registry` fetchers on its own connection.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_refresh_api.py
import threading
import time

import pytest
from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    init_db(path).close()
    return str(path)


def test_refresh_runs_fake_pipeline_and_reports_result(db_path):
    def fake_runner(path, on_stage):
        on_stage("ingesting")
        on_stage("scoring")
        return {"ingest": {"new_jobs": 3}, "embed_scored": 3, "embed_skipped": None}

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=fake_runner))
    assert tc.post("/api/refresh").json() == {"started": True}

    deadline = time.time() + 5
    while time.time() < deadline:
        body = tc.get("/api/refresh/status").json()
        if not body["running"] and body["stage"] == "done":
            break
        time.sleep(0.02)
    assert body["stage"] == "done"
    assert body["last_result"]["ingest"]["new_jobs"] == 3
    assert body["error"] is None


def test_refresh_409_while_running(db_path):
    release = threading.Event()

    def slow_runner(path, on_stage):
        release.wait(timeout=5)
        return {"ingest": {"new_jobs": 0}, "embed_scored": 0, "embed_skipped": None}

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=slow_runner))
    assert tc.post("/api/refresh").status_code == 200
    assert tc.post("/api/refresh").status_code == 409
    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and tc.get("/api/refresh/status").json()["running"]:
        time.sleep(0.02)
    assert tc.post("/api/refresh").status_code == 200  # can run again after finish
    deadline = time.time() + 5
    while time.time() < deadline and tc.get("/api/refresh/status").json()["running"]:
        time.sleep(0.02)


def test_refresh_error_surfaces_in_status(db_path):
    def broken_runner(path, on_stage):
        raise RuntimeError("source exploded")

    tc = TestClient(create_app(db_path=db_path, pipeline_runner=broken_runner))
    tc.post("/api/refresh")
    deadline = time.time() + 5
    while time.time() < deadline:
        body = tc.get("/api/refresh/status").json()
        if body["stage"] == "error":
            break
        time.sleep(0.02)
    assert body["stage"] == "error"
    assert "source exploded" in body["error"]
    assert body["running"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_refresh_api.py -v`
Expected: FAIL (`POST /api/refresh` → 404 / import errors)

- [ ] **Step 3: Implement `refresh_job.py`**

```python
# src/job_dashboard/api/refresh_job.py
import threading

from job_dashboard.db import init_db
from job_dashboard.pipeline import run_pipeline
from job_dashboard.source_registry import company_sources, job_sources


class RefreshState:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self.stage = "idle"
        self.detail = None
        self.last_result = None
        self.error = None

    def snapshot(self):
        with self._lock:
            return {
                "running": self._running, "stage": self.stage,
                "detail": self.detail, "last_result": self.last_result,
                "error": self.error,
            }

    def start(self, runner):
        """runner(on_stage) -> result dict. Returns False if already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self.stage = "starting"
            self.error = None

        def on_stage(stage):
            with self._lock:
                self.stage = stage

        def work():
            try:
                result = runner(on_stage)
                with self._lock:
                    self.last_result = result
                    self.stage = "done"
                    self.detail = _summarize(result)
            except Exception as exc:
                with self._lock:
                    self.stage = "error"
                    self.error = str(exc)
            finally:
                with self._lock:
                    self._running = False

        threading.Thread(target=work, daemon=True).start()
        return True


def _summarize(result):
    ingest = result.get("ingest", {})
    parts = [f"{ingest.get('new_jobs', 0)} new jobs",
             f"{result.get('embed_scored', 0)} scored"]
    if result.get("embed_skipped"):
        parts.append(f"scoring skipped: {result['embed_skipped']}")
    return ", ".join(parts)


def default_pipeline_runner(db_path, on_stage):
    conn = init_db(db_path)  # own connection: sqlite is per-thread
    try:
        return run_pipeline(conn, job_sources(), company_sources(), on_stage=on_stage)
    finally:
        conn.close()
```

- [ ] **Step 4: Wire endpoints into `create_app`**

In `app.py`: `create_app(db_path=DEFAULT_DB, pipeline_runner=None)`; inside, after the existing endpoints:

```python
    from job_dashboard.api.refresh_job import RefreshState, default_pipeline_runner

    state = RefreshState()
    runner = pipeline_runner or default_pipeline_runner

    @app.post("/api/refresh")
    def start_refresh():
        started = state.start(lambda on_stage: runner(db_path, on_stage))
        if not started:
            raise HTTPException(status_code=409, detail="refresh already running")
        return {"started": True}

    @app.get("/api/refresh/status")
    def refresh_status():
        return state.snapshot()
```

(Move the `from ... import` to the top of the file with the other imports.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_refresh_api.py tests/test_api.py -v`
Expected: PASS (3 + 5)

- [ ] **Step 6: Full suite + commit**

Run: `python3 -m pytest` → all pass.

```bash
git add src/job_dashboard/api/refresh_job.py src/job_dashboard/api/app.py tests/test_refresh_api.py
git commit -m "feat: background refresh job with stage reporting and 409 guard"
```

---

### Task 5: Frontend scaffold — Vite + React + pastel tokens + API client + app shell

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/main.jsx`, `frontend/src/App.jsx`, `frontend/src/api.js`, `frontend/src/components/icons.jsx`, `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css`, `frontend/src/__tests__/smoke.test.jsx`
- Modify: `.gitignore` (add `node_modules/`, `frontend/dist/`)

**Interfaces:**
- Produces: `api.js` exporting `fetchJobs(params)`, `fetchJob(id)`, `patchStatus(id, status)`, `fetchDuplicates()`, `fetchStats()`, `startRefresh()`, `refreshStatus()` — all `fetch`-based, JSON, throwing on non-OK (except 409 → `{alreadyRunning: true}`).
- Produces: `tokens.css` custom properties consumed by all later components: `--pastel-lavender/-ink`, `--pastel-mint/-ink`, `--pastel-peach/-ink`, `--pastel-pink/-ink`, `--radius-row: 12px`, `--radius-card: 16px`, `--dur-quick: 150ms`, `--dur-enter: 450ms`, `--ease-pop: cubic-bezier(0.34,1.4,0.64,1)`, `--ease-out: cubic-bezier(0.22,1,0.36,1)`.
- Produces: `App.jsx` shell holding state: `filters`, `jobs`, `total`, `stats`, `selectedId`, `refresh` — later tasks fill in components.

- [ ] **Step 1: Verify node/npm are available**

```bash
node --version && npm --version
```
Expected: v18+. If missing: `brew install node`, then re-run.

- [ ] **Step 2: Write the scaffold files**

```json
// frontend/package.json
{
  "name": "job-dashboard-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^24.0.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
```

```javascript
// frontend/vite.config.js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", setupFiles: [], globals: true },
});
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Job dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

```css
/* frontend/src/styles/tokens.css */
:root {
  --pastel-lavender: #EEEDFE; --pastel-lavender-ink: #3C3489; --pastel-lavender-mid: #534AB7;
  --pastel-mint: #E1F5EE;     --pastel-mint-ink: #085041;     --pastel-mint-mid: #0F6E56;
  --pastel-peach: #FAEEDA;    --pastel-peach-ink: #633806;    --pastel-peach-mid: #854F0B;
  --pastel-pink: #FBEAF0;     --pastel-pink-ink: #72243E;     --pastel-pink-mid: #993556;
  --paper: #FFFFFF; --paper-dim: #F7F6F3; --ink: #2C2C2A; --ink-soft: #787774; --ink-faint: #9B9A94;
  --hairline: rgba(44, 44, 42, 0.06);
  --radius-row: 8px; --radius-card: 12px; --radius-pill: 999px;
  --font-sans: 'SF Pro Display', 'Helvetica Neue', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'JetBrains Mono', ui-monospace, monospace;
  --dur-quick: 200ms; --dur-enter: 600ms;
  --ease-pop: cubic-bezier(0.34, 1.4, 0.64, 1);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --hover-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1E1E1C; --paper-dim: #262624; --ink: #F1EFE8; --ink-soft: #B4B2A9; --ink-faint: #888780;
    --hairline: rgba(241, 239, 232, 0.14);
    --pastel-lavender: #26215C; --pastel-lavender-ink: #CECBF6; --pastel-lavender-mid: #AFA9EC;
    --pastel-mint: #04342C;     --pastel-mint-ink: #9FE1CB;     --pastel-mint-mid: #5DCAA5;
    --pastel-peach: #412402;    --pastel-peach-ink: #FAC775;    --pastel-peach-mid: #EF9F27;
    --pastel-pink: #4B1528;     --pastel-pink-ink: #F4C0D1;     --pastel-pink-mid: #ED93B1;
  }
}
```

```css
/* frontend/src/styles/app.css */
@import "./tokens.css";
* { box-sizing: border-box; }
body { margin: 0; font-family: var(--font-sans); background: var(--paper-dim); color: var(--ink); }
.shell { max-width: 1100px; margin: 0 auto; padding: 32px 16px; }
.meta { font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.05em; }
@keyframes rowIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes popIn { from { opacity: 0; transform: scale(0.85); } to { opacity: 1; transform: scale(1); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.06); } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

```javascript
// frontend/src/api.js
async function json(resp) {
  if (resp.status === 409) return { alreadyRunning: true };
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

export function fetchJobs(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")
  );
  return fetch(`/api/jobs?${qs}`).then(json);
}
export const fetchJob = (id) => fetch(`/api/jobs/${id}`).then(json);
export const patchStatus = (id, status) =>
  fetch(`/api/jobs/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).then(json);
export const fetchDuplicates = () => fetch("/api/duplicates").then(json);
export const fetchStats = () => fetch("/api/stats").then(json);
export const startRefresh = () => fetch("/api/refresh", { method: "POST" }).then(json);
export const refreshStatus = () => fetch("/api/refresh/status").then(json);
```

```javascript
// frontend/src/components/icons.jsx
import React from "react";

const base = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none",
               stroke: "currentColor", strokeWidth: 2.5, strokeLinecap: "round",
               strokeLinejoin: "round", "aria-hidden": true };

export const CheckIcon = () => (
  <svg {...base}><path d="M5 13l4 4L19 7" /></svg>
);
export const XIcon = () => (
  <svg {...base}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const RefreshIcon = ({ spinning }) => (
  <svg {...base} style={spinning ? { animation: "spin 0.9s linear infinite" } : undefined}>
    <path d="M20 11A8 8 0 1 0 4.6 14M20 11V5m0 6h-6" />
  </svg>
);
export const ChevronIcon = ({ open }) => (
  <svg {...base} style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform var(--dur-quick) ease-out" }}>
    <path d="M6 9l6 6 6-6" />
  </svg>
);
```

```javascript
// frontend/src/main.jsx
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles/app.css";

createRoot(document.getElementById("root")).render(<App />);
```

```javascript
// frontend/src/App.jsx
import React, { useCallback, useEffect, useState } from "react";
import { fetchJobs, fetchStats } from "./api.js";

export default function App() {
  const [filters, setFilters] = useState({ sort: "embed" });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    Promise.all([fetchJobs(filters), fetchStats()])
      .then(([feed, s]) => {
        setJobs(feed.jobs); setTotal(feed.total); setStats(s); setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [filters]);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="shell">
      <header style={{ background: "var(--pastel-lavender)", borderRadius: "var(--radius-card)", padding: "16px 20px" }}>
        <h1 style={{ fontSize: 17, fontWeight: 500, color: "var(--pastel-lavender-ink)", margin: 0 }}>
          Job dashboard
        </h1>
        {stats && (
          <span data-testid="stats" style={{ fontSize: 12, color: "var(--pastel-lavender-mid)" }}>
            {stats.total} jobs · {stats.new} new
          </span>
        )}
      </header>
      {error && <div role="alert" style={{ color: "var(--pastel-pink-ink)", background: "var(--pastel-pink)", borderRadius: 12, padding: "10px 14px", marginTop: 12 }}>{error}</div>}
      <main data-testid="feed-slot">
        <ul data-testid="job-list">
          {jobs.map((j) => (
            <li key={j.id}>{j.title} — {j.company}</li>
          ))}
        </ul>
        <span data-testid="total">{total}</span>
      </main>
    </div>
  );
}
```

```javascript
// frontend/src/__tests__/smoke.test.jsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "../App.jsx";

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/stats")
      ? { total: 2, new: 1, saved: 0, applied: 1, dismissed: 0, unranked: 1 }
      : { jobs: [{ id: 1, title: "ML Engineer", company: "Stripe" },
                 { id: 2, title: "AI Engineer", company: "Acme" }], total: 2 };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
});

test("renders feed and stats from the API", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText(/ML Engineer/)).toBeDefined());
  expect(screen.getByTestId("stats").textContent).toContain("2 jobs");
  expect(screen.getByTestId("total").textContent).toBe("2");
});
```

- [ ] **Step 3: Install and run the failing→passing cycle**

```bash
cd frontend && npm install && npx vitest run
```
Expected: 1 test passes. (The RED step for scaffolding is the `npm install`/import failure before files exist; the meaningful TDD cycles are in Tasks 6–7.)

- [ ] **Step 4: Update `.gitignore`**

Append:
```
node_modules/
frontend/dist/
```

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/index.html frontend/src .gitignore
git commit -m "feat: Vite+React frontend scaffold with pastel tokens and API client"
```
(`package-lock.json` is committed deliberately — reproducible installs.)

---

### Task 6: Feed — FilterBar, job rows, ScoreBadge with count-up, staggered entrance

**Files:**
- Create: `frontend/src/components/FilterBar.jsx`, `frontend/src/components/Feed.jsx`, `frontend/src/components/ScoreBadge.jsx`
- Modify: `frontend/src/App.jsx` (mount them)
- Test: `frontend/src/__tests__/feed.test.jsx`

**Interfaces:**
- Consumes: `App`'s `filters/setFilters`, `jobs`, `selectedId/setSelectedId`.
- Produces: `<FilterBar filters setFilters />`, `<Feed jobs selectedId onSelect />`, `<ScoreBadge value />` (count-up to `Math.round(embed_score*100)`; respects reduced motion).

- [ ] **Step 1: Write the failing tests**

```javascript
// frontend/src/__tests__/feed.test.jsx
import { fireEvent, render, screen } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import Feed from "../components/Feed.jsx";
import FilterBar from "../components/FilterBar.jsx";

const JOBS = [
  { id: 1, title: "ML Engineer", company: "Stripe", location: "Remote", source: "remotive",
    posted_date: "2026-07-11", embed_score: 0.87, llm_score: 87, verdict: "Strong Fit", status: null },
  { id: 2, title: "AI Engineer", company: "Acme", location: "Remote", source: "jobspy:linkedin",
    posted_date: "2026-07-12", embed_score: 0.76, llm_score: null, verdict: null, status: "applied" },
];

test("renders rows with verdict pill, ranking placeholder, and status chip", () => {
  render(<Feed jobs={JOBS} selectedId={null} onSelect={() => {}} />);
  expect(screen.getByText("Strong Fit")).toBeDefined();
  expect(screen.getByText("Ranking…")).toBeDefined();
  expect(screen.getByText(/applied/)).toBeDefined();
});

test("clicking a row selects it", () => {
  const onSelect = vi.fn();
  render(<Feed jobs={JOBS} selectedId={null} onSelect={onSelect} />);
  fireEvent.click(screen.getByText("ML Engineer"));
  expect(onSelect).toHaveBeenCalledWith(1);
});

test("rows get staggered animation delays", () => {
  render(<Feed jobs={JOBS} selectedId={null} onSelect={() => {}} />);
  const rows = screen.getAllByRole("listitem");
  expect(rows[0].style.animationDelay).toBe("0ms");
  expect(rows[1].style.animationDelay).toBe("80ms");
});

test("filter chips toggle and propagate", () => {
  const setFilters = vi.fn();
  render(<FilterBar filters={{ sort: "embed" }} setFilters={setFilters} />);
  fireEvent.click(screen.getByText("Remote"));
  expect(setFilters).toHaveBeenCalled();
  const updater = setFilters.mock.calls[0][0];
  expect(updater({ sort: "embed" })).toEqual({ sort: "embed", remote: true });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run`
Expected: FAIL — components don't exist.

- [ ] **Step 3: Implement the components**

```javascript
// frontend/src/components/ScoreBadge.jsx
import React, { useEffect, useState } from "react";

export default function ScoreBadge({ value }) {
  const target = value == null ? null : Math.round(value * 100);
  const reduced = typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(reduced ? target : 0);

  useEffect(() => {
    if (target == null || reduced) { setShown(target); return; }
    let raf, start = null;
    const step = (ts) => {
      if (start == null) start = ts;
      const p = Math.min((ts - start) / 900, 1);
      setShown(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, reduced]);

  if (target == null) return <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>—</span>;
  return (
    <span style={{ fontSize: 16, fontWeight: 500, color: "var(--pastel-lavender-mid)", minWidth: 26, textAlign: "right" }}>
      {shown}
    </span>
  );
}
```

```javascript
// frontend/src/components/Feed.jsx
import React from "react";
import ScoreBadge from "./ScoreBadge.jsx";

function monogram(company) {
  return (company || "?").slice(0, 2);
}

const PILL = { fontSize: 11, padding: "3px 10px", borderRadius: "var(--radius-pill)" };

export default function Feed({ jobs, selectedId, onSelect }) {
  if (!jobs.length) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0", color: "var(--ink-soft)" }}>
        <p style={{ margin: 0 }}>No jobs yet — hit refresh to pull the boards.</p>
      </div>
    );
  }
  return (
    <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0, background: "var(--paper)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
      {jobs.map((j, i) => (
        <li
          key={j.id}
          role="listitem"
          onClick={() => onSelect(j.id)}
          style={{
            animation: "rowIn var(--dur-enter) var(--ease-out) both",
            animationDelay: `${i * 80}ms`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "13px 20px", cursor: "pointer",
            borderTop: i ? "0.5px solid var(--hairline)" : "none",
            background: j.id === selectedId ? "var(--pastel-lavender)" : "transparent",
            opacity: j.status === "dismissed" || j.status === "applied" ? 0.75 : 1,
            transition: "transform var(--dur-quick) ease-out, background var(--dur-quick) ease-out",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "translateX(4px)"; e.currentTarget.style.boxShadow = "var(--hover-shadow)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "none"; }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 38, height: 38, borderRadius: 8, background: "var(--pastel-lavender)", color: "var(--pastel-lavender-ink)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 500, fontSize: 13 }}>
              {monogram(j.company)}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                {j.title}
                {j.status && (
                  <span style={{ ...PILL, background: "var(--pastel-peach)", color: "var(--pastel-peach-mid)", marginLeft: 8 }}>
                    {j.status}
                  </span>
                )}
              </div>
              <div className="meta" style={{ color: "var(--ink-soft)" }}>
                {j.company} · {j.location || "—"} · {j.posted_date || ""} · {j.source}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {j.verdict ? (
              <span style={{ ...PILL, background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)", animation: "popIn 0.4s var(--ease-pop) both", animationDelay: `${300 + i * 100}ms` }}>
                {j.verdict}
              </span>
            ) : (
              <span style={{ ...PILL, background: "var(--paper-dim)", color: "var(--ink-faint)" }}>Ranking…</span>
            )}
            <ScoreBadge value={j.embed_score} />
          </div>
        </li>
      ))}
    </ul>
  );
}
```

```javascript
// frontend/src/components/FilterBar.jsx
import React from "react";
import { CheckIcon } from "./icons.jsx";

const CHIPS = [
  { key: "remote", label: "Remote", on: { background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)" } },
  { key: "job_type", label: "Full-time", value: "fulltime", on: { background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)" } },
  { key: "status", label: "Saved", value: "saved", on: { background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)" } },
];

export default function FilterBar({ filters, setFilters }) {
  const toggle = (key, value = true) =>
    setFilters((f) => {
      const next = { ...f };
      if (next[key] === value) delete next[key];
      else next[key] = value;
      return next;
    });

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "12px 0 0" }}>
      <input
        type="search"
        placeholder="Search roles, companies…"
        aria-label="Search jobs"
        onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
        style={{ flex: 1, minWidth: 150, border: "none", background: "var(--paper)", borderRadius: "var(--radius-pill)", padding: "8px 14px", fontSize: 13, color: "var(--ink)" }}
      />
      {CHIPS.map((c) => {
        const active = filters[c.key] === (c.value ?? true);
        return (
          <button
            key={c.label}
            onClick={() => toggle(c.key, c.value ?? true)}
            style={{
              border: "none", cursor: "pointer", fontSize: 12, padding: "6px 12px",
              borderRadius: "var(--radius-pill)",
              transition: "transform var(--dur-quick) ease-out",
              ...(active ? c.on : { background: "var(--paper)", color: "var(--ink-soft)" }),
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; }}
          >
            {c.label}{active && <CheckIcon />}
          </button>
        );
      })}
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 6, alignItems: "center" }}>
        Sort
        <select
          value={filters.sort}
          onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}
          style={{ border: "none", background: "var(--paper)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}
        >
          <option value="embed">match score</option>
          <option value="llm">LLM score</option>
          <option value="date">newest</option>
        </select>
      </label>
      <label style={{ fontSize: 12, color: "var(--ink-faint)", display: "flex", gap: 4, alignItems: "center" }}>
        <input type="checkbox" checked={!!filters.include_dismissed}
          onChange={(e) => setFilters((f) => ({ ...f, include_dismissed: e.target.checked || undefined }))} />
        show dismissed
      </label>
    </div>
  );
}
```

In `App.jsx`, replace the `<main>` placeholder with:

```javascript
      <FilterBar filters={filters} setFilters={setFilters} />
      <Feed jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} />
```
(with the imports `import FilterBar from "./components/FilterBar.jsx"; import Feed from "./components/Feed.jsx";`). Keep `data-testid="stats"`; the smoke test's `job-list`/`total` testids are superseded — update `smoke.test.jsx` to assert on `screen.getByText(/ML Engineer/)` and `stats` only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run`
Expected: PASS (smoke + 4 feed tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: pastel feed with filters, staggered entrance, count-up scores"
```

---

### Task 7: JobDetail panel, RefreshButton with polling, DuplicatesSection

**Files:**
- Create: `frontend/src/components/JobDetail.jsx`, `frontend/src/components/RefreshButton.jsx`, `frontend/src/components/DuplicatesSection.jsx`
- Modify: `frontend/src/App.jsx`
- Test: `frontend/src/__tests__/detail.test.jsx`

**Interfaces:**
- Consumes: `api.js` functions; `App`'s `selectedId`, `reload`.
- Produces: `<JobDetail id onStatusChange onClose />` (fetches detail on mount/id change; Save/Applied/Dismiss buttons PATCH then call `onStatusChange`), `<RefreshButton onDone />` (starts refresh, polls status every 1s while running, shows stage; warning banner on `embed_skipped`; disabled/409-safe), `<DuplicatesSection />` (collapsed count strip; expands to list; no delete affordance).

- [ ] **Step 1: Write the failing tests**

```javascript
// frontend/src/__tests__/detail.test.jsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import JobDetail from "../components/JobDetail.jsx";
import DuplicatesSection from "../components/DuplicatesSection.jsx";

const DETAIL = {
  id: 1, title: "ML Engineer", company: "Stripe", location: "Remote",
  job_url: "https://x.com/1", status: null, embed_score: 0.81, llm_score: 87,
  verdict: "Strong Fit", description: "Own fraud models end-to-end.",
  strengths: ["prod ML"], gaps: ["k8s"], flags: { expired: false },
  cross_listings: [{ id: 3, source: "remoteok", job_url: "https://r.ok/3" }],
};

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (opts && opts.method === "PATCH")
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    if (String(url).includes("/api/duplicates"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        duplicates: [{ id: 3, title: "ML Engineer", company: "Stripe", source: "remoteok",
                       job_url: "https://r.ok/3", duplicate_of: 1, canonical_source: "remotive" }] }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DETAIL) });
  });
});

test("detail shows JD, scores, strengths/gaps, cross-listings", async () => {
  render(<JobDetail id={1} onStatusChange={() => {}} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/Own fraud models/)).toBeDefined());
  expect(screen.getByText("prod ML")).toBeDefined();
  expect(screen.getByText("k8s")).toBeDefined();
  expect(screen.getByText(/remoteok/)).toBeDefined();
});

test("status buttons PATCH and notify", async () => {
  const onStatusChange = vi.fn();
  render(<JobDetail id={1} onStatusChange={onStatusChange} onClose={() => {}} />);
  await waitFor(() => screen.getByText("Save"));
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(onStatusChange).toHaveBeenCalled());
  const patchCall = global.fetch.mock.calls.find(([, o]) => o && o.method === "PATCH");
  expect(patchCall[0]).toBe("/api/jobs/1/status");
  expect(JSON.parse(patchCall[1].body)).toEqual({ status: "saved" });
});

test("duplicates section expands and has no delete button", async () => {
  render(<DuplicatesSection />);
  await waitFor(() => screen.getByText(/Suspected duplicates/));
  fireEvent.click(screen.getByText(/Suspected duplicates/));
  await waitFor(() => expect(screen.getByText(/duplicate of #1/)).toBeDefined());
  expect(screen.queryByText(/delete/i)).toBeNull();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run`
Expected: FAIL — components don't exist.

- [ ] **Step 3: Implement the components**

```javascript
// frontend/src/components/JobDetail.jsx
import React, { useEffect, useState } from "react";
import { fetchJob, patchStatus } from "../api.js";
import { XIcon } from "./icons.jsx";

const BTN = { border: "none", cursor: "pointer", fontSize: 12, padding: "6px 14px", borderRadius: "var(--radius-pill)", transition: "transform var(--dur-quick) ease-out" };

export default function JobDetail({ id, onStatusChange, onClose }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setJob(null);
    fetchJob(id).then(setJob).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <div role="alert" style={{ padding: 16, color: "var(--pastel-pink-ink)" }}>{error}</div>;
  if (!job) return <div style={{ padding: 16, color: "var(--ink-faint)" }}>Loading…</div>;

  const setStatus = (status) =>
    patchStatus(id, status).then(() => onStatusChange(status)).catch((e) => setError(String(e)));

  return (
    <div style={{ background: "var(--paper)", borderRadius: "var(--radius-card)", padding: "18px 20px", marginTop: 14, animation: "rowIn var(--dur-enter) var(--ease-out) both" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 500 }}>{job.title}</div>
          <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>{job.company} · {job.location || "—"} · via {job.source}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {job.embed_score != null && (
            <div style={{ textAlign: "center", background: "var(--pastel-lavender)", borderRadius: 14, padding: "8px 16px" }}>
              <div style={{ fontSize: 22, fontWeight: 500, color: "var(--pastel-lavender-ink)" }}>
                {job.llm_score ?? Math.round(job.embed_score * 100)}
              </div>
              <div style={{ fontSize: 10, color: "var(--pastel-lavender-mid)" }}>
                {job.llm_score != null ? `embed ${job.embed_score.toFixed(2)} · LLM ${job.llm_score}` : "embed match"}
              </div>
            </div>
          )}
          <button onClick={onClose} aria-label="Close" style={{ ...BTN, background: "var(--paper-dim)", color: "var(--ink-faint)" }}><XIcon /></button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "14px 0" }}>
        <button style={{ ...BTN, background: "var(--pastel-mint)", color: "var(--pastel-mint-ink)" }} onClick={() => setStatus("saved")}>Save</button>
        <button style={{ ...BTN, background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)" }} onClick={() => setStatus("applied")}>Applied</button>
        <button style={{ ...BTN, background: "var(--paper-dim)", color: "var(--ink-faint)" }} onClick={() => setStatus("dismissed")}>Dismiss</button>
        <a href={job.job_url} target="_blank" rel="noreferrer"
           style={{ ...BTN, background: "var(--pastel-lavender)", color: "var(--pastel-lavender-ink)", marginLeft: "auto", textDecoration: "none" }}>
          Apply ↗
        </a>
      </div>

      {(job.strengths.length > 0 || job.gaps.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ background: "var(--pastel-mint)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--pastel-mint-ink)", marginBottom: 4 }}>Strengths</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--pastel-mint-mid)", lineHeight: 1.6 }}>
              {job.strengths.map((s) => <li key={s}>{s}</li>)}
            </ul>
          </div>
          <div style={{ background: "var(--pastel-peach)", borderRadius: 12, padding: "12px 14px" }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: "var(--pastel-peach-ink)", marginBottom: 4 }}>Gaps</div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "var(--pastel-peach-mid)", lineHeight: 1.6 }}>
              {job.gaps.map((g) => <li key={g}>{g}</li>)}
            </ul>
          </div>
        </div>
      )}

      <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 12, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
        {job.description}
      </div>

      {job.cross_listings.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 10 }}>
          Also posted on: {job.cross_listings.map((c) => c.source).join(", ")}
        </div>
      )}
    </div>
  );
}
```

```javascript
// frontend/src/components/RefreshButton.jsx
import React, { useEffect, useRef, useState } from "react";
import { refreshStatus, startRefresh } from "../api.js";
import { RefreshIcon } from "./icons.jsx";

export default function RefreshButton({ onDone }) {
  const [status, setStatus] = useState({ running: false, stage: "idle" });
  const timer = useRef(null);

  const poll = () => {
    refreshStatus().then((s) => {
      setStatus(s);
      if (s.running) timer.current = setTimeout(poll, 1000);
      else if (s.stage === "done" || s.stage === "error") onDone(s);
    });
  };

  useEffect(() => () => clearTimeout(timer.current), []);

  const click = () =>
    startRefresh().then(() => poll());

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {status.stage === "error" && (
        <span role="alert" style={{ fontSize: 11, color: "var(--pastel-pink-ink)" }}>refresh failed: {status.error}</span>
      )}
      {status.last_result?.embed_skipped && (
        <span role="alert" style={{ fontSize: 11, background: "var(--pastel-peach)", color: "var(--pastel-peach-ink)", borderRadius: 8, padding: "3px 8px" }}>
          scoring skipped: {status.last_result.embed_skipped}
        </span>
      )}
      <button
        onClick={click}
        disabled={status.running}
        style={{ border: "none", cursor: status.running ? "wait" : "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6, background: "var(--paper)", borderRadius: "var(--radius-pill)", padding: "7px 16px", color: "var(--pastel-lavender-ink)" }}
      >
        <RefreshIcon spinning={status.running} />
        {status.running ? status.stage : "Refresh"}
      </button>
    </span>
  );
}
```

```javascript
// frontend/src/components/DuplicatesSection.jsx
import React, { useEffect, useState } from "react";
import { fetchDuplicates } from "../api.js";
import { ChevronIcon } from "./icons.jsx";

export default function DuplicatesSection() {
  const [dupes, setDupes] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => { fetchDuplicates().then((b) => setDupes(b.duplicates)).catch(() => {}); }, []);

  if (!dupes.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ border: "none", cursor: "pointer", width: "100%", textAlign: "left", background: "var(--pastel-pink)", color: "var(--pastel-pink-ink)", borderRadius: open ? "12px 12px 0 0" : 12, padding: "11px 16px", fontSize: 13 }}
      >
        Suspected duplicates ({dupes.length}) — kept safe, never deleted <ChevronIcon open={open} />
      </button>
      {open && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, background: "var(--paper)", borderRadius: "0 0 12px 12px" }}>
          {dupes.map((d) => (
            <li key={d.id} style={{ padding: "10px 16px", borderTop: "0.5px solid var(--hairline)", fontSize: 12, color: "var(--ink-soft)" }}>
              {d.title} — {d.company} <span style={{ color: "var(--ink-faint)" }}>({d.source})</span>
              <span style={{ float: "right", color: "var(--pastel-pink-mid)" }}>duplicate of #{d.duplicate_of} · {d.canonical_source}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

In `App.jsx`: import the three; put `<RefreshButton onDone={reload} />` inside the header (flex row, `justifyContent: "space-between"`); render `{selectedId && <JobDetail id={selectedId} onStatusChange={() => reload()} onClose={() => setSelectedId(null)} />}` after the Feed; `<DuplicatesSection />` last. Add a breathing live-dot next to the stats: `<span aria-hidden="true" style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: "var(--pastel-mint-mid)", marginRight: 5, animation: "breathe 2.2s ease-in-out infinite" }} />`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run`
Expected: PASS (all frontend tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: job detail panel, polling refresh button, duplicates section"
```

---

### Task 8: Static serving + end-to-end smoke run

**Files:**
- Modify: `src/job_dashboard/api/app.py` (serve `frontend/dist` when present)
- Create: `.claude/launch.json`

**Interfaces:**
- Produces: `create_app` mounts `frontend/dist` at `/` (SPA fallback to `index.html`) when the directory exists; API routes keep priority.

- [ ] **Step 1: Add static serving to `create_app`** (after all routes, before `return app`):

```python
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
```

- [ ] **Step 2: Verify API tests still pass** (routes registered before the mount keep priority):

Run: `python3 -m pytest tests/test_api.py tests/test_refresh_api.py -v`
Expected: PASS

- [ ] **Step 3: Build the frontend and smoke-run the whole app**

```bash
cd frontend && npm run build && cd ..
python3 -c "
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
import pathlib
pathlib.Path('data').mkdir(exist_ok=True)
conn = init_db('data/jobs.db')
insert_job(conn, JobListing(source='smoke', title='Smoke Test Role', company='SmokeCo',
                            job_url='https://example.com/smoke-1', description='smoke jd'))
print('seeded')
"
python3 -m uvicorn job_dashboard.api.app:app --port 8000 &
sleep 2
curl -s http://127.0.0.1:8000/api/jobs | head -c 200; echo
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
kill %1
```
Expected: JSON with `Smoke Test Role`; `200` for the SPA index.

- [ ] **Step 4: Write `.claude/launch.json`**

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "dashboard",
      "runtimeExecutable": "python3",
      "runtimeArgs": ["-m", "uvicorn", "job_dashboard.api.app:app", "--port", "8000"],
      "port": 8000
    },
    {
      "name": "frontend-dev",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["--prefix", "frontend", "run", "dev"],
      "port": 5173
    }
  ]
}
```

- [ ] **Step 5: Full backend suite one last time**

Run: `python3 -m pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/api/app.py .claude/launch.json
git commit -m "feat: serve built frontend from FastAPI; launch config; e2e smoke"
```

---

## After this plan (not tasks — session-level follow-ups)

1. **Taste pass:** the `minimalist-ui` skill's rules are now baked into the Global Constraints and Task 5 tokens (fonts, text colors, hairlines, radii, motion physics, SVG-only icons — with one documented pastel deviation per user preference). The post-build taste pass is therefore a verification sweep, not a retrofit: confirm the built UI matches the discipline block.
2. **impeccable pass:** `/impeccable audit` + `polish` against the running app in the browser — explicit audit points: pastel-fill contrast (dark end of same family), `prefers-reduced-motion`, empty/error states, keyboard navigation.
3. First real refresh run (needs `pip3 install sentence-transformers` + network).

## What this plan does not cover (spec Non-goals)

- Application tracking beyond the status field; cover letters; resume engine; outreach.
- Deleting suspected duplicates (explicit user command, later).
- Mobile-optimized layout; auth/hosting.
