# Company Research Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Dispatch prompts in caveman style (project memory).

**Goal:** Let the user curate 1–2 web sources per company from auto-gathered search results, saved against the company name, and ground the cover-letter draft only in those picks.

**Architecture:** A pure grouping helper (`letter/research_store.py`) turns the existing `company_research` bundle into ranked per-source `Resource`s. A `company_resources` table (db.py, keyed by normalized company name) stores them with a `selected` flag. `DefaultLetterEngine` gains gather/list/select methods; the draft grounds in selected resources (fallback: top-2). `CoverLetterPanel` adds a "Find company research" curation step. Everything else (grounding guard, render, never-send) is unchanged.

**Tech Stack:** Python 3.11+, sqlite3, FastAPI, pytest (fake engine — no network/LLM/LaTeX in unit tests), React + Vitest.

## Global Constraints

- Resource = a SOURCE: `(source_url, title, summary)`. `summary` = the top 1–2 extracted fact-sentences from that URL, verbatim (no extra LLM call). `title` = the URL host (scheme + leading `www.` stripped).
- `company_key` = `company.strip().lower()`, internal whitespace collapsed, a single trailing `inc/llc/ltd/corp/co` token removed. All jobs at one company share a list.
- Re-running gather **upserts** (refresh title/summary, PRESERVE `selected`). Select persists per company; **max 2** selected.
- Draft grounds in SELECTED resources; none selected → top-2 of the saved list; no resources saved at all → today's fresh `company_research` behavior. Draft never blocks, never 500s on TinyFish/Ollama down.
- No test performs a real TinyFish/Ollama/LaTeX/network call except explicitly-skipped live smokes. API tests inject a fake `letter_engine`.
- Never a send/apply control anywhere. db.py stays SQL-only.
- Existing suite (226 pytest + 37 vitest) stays green.

---

### Task 1: `research_store.py` — group a bundle into per-source resources

**Files:**
- Create: `src/job_dashboard/letter/research_store.py`
- Test: `tests/test_research_store.py`

**Interfaces:**
- Consumes: `job_dashboard.letter.company_research.ResearchBundle`, `Fact` (`Fact(text, source_url)`).
- Produces: `Resource` dataclass `(source_url: str, title: str, summary: str)`; `resources_from_bundle(bundle: ResearchBundle) -> list[Resource]` (≤6, order preserves the bundle's fact ranking, one Resource per unique `source_url`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_research_store.py
from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.letter.research_store import Resource, resources_from_bundle


def _bundle(facts):
    return ResearchBundle(facts=facts, queries_used=[], empty=not facts)


def test_groups_facts_by_source_url_into_one_resource_each():
    b = _bundle([
        Fact("JPMorgan built a data mesh architecture.", "https://aws.amazon.com/blogs/x"),
        Fact("It cut costs and improved data access.", "https://aws.amazon.com/blogs/x"),
        Fact("Account Confidence Score is an AI/ML fraud score.", "https://www.jpmorgan.com/acs"),
    ])
    res = resources_from_bundle(b)
    assert [r.source_url for r in res] == [
        "https://aws.amazon.com/blogs/x", "https://www.jpmorgan.com/acs"]
    # summary joins the source's top facts; title is the host
    assert "data mesh" in res[0].summary and "improved data access" in res[0].summary
    assert res[0].title == "aws.amazon.com"
    assert res[1].title == "jpmorgan.com"


def test_title_strips_www_and_scheme():
    b = _bundle([Fact("Launched a real-time ranking service.", "https://www.nike.com/tech")])
    assert resources_from_bundle(b)[0].title == "nike.com"


def test_caps_at_six_resources():
    facts = [Fact(f"Fact {i} with $1{i}M revenue.", f"https://ex{i}.com/") for i in range(9)]
    assert len(resources_from_bundle(_bundle(facts))) == 6


def test_empty_bundle_yields_no_resources():
    assert resources_from_bundle(_bundle([])) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_research_store.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `research_store.py`**

```python
"""Group a ResearchBundle into per-source Resources for user curation.

Pure logic: one Resource per unique source_url, the URL's top 1-2 fact texts
joined as its summary, order preserving the bundle's existing fact ranking,
capped at _MAX_RESOURCES. No I/O, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

from job_dashboard.letter.company_research import ResearchBundle

_MAX_RESOURCES = 6
_MAX_SUMMARY_CHARS = 240
_MAX_FACTS_PER_SOURCE = 2


@dataclass
class Resource:
    source_url: str
    title: str
    summary: str


def _host(url: str) -> str:
    host = (url or "").split("//", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def resources_from_bundle(bundle: ResearchBundle) -> list[Resource]:
    facts = getattr(bundle, "facts", None) or []
    by_url: dict[str, list[str]] = {}
    order: list[str] = []
    for f in facts:
        url = getattr(f, "source_url", "") or ""
        text = getattr(f, "text", "") or ""
        if not url or not text:
            continue
        if url not in by_url:
            by_url[url] = []
            order.append(url)
        by_url[url].append(text)

    resources: list[Resource] = []
    for url in order[:_MAX_RESOURCES]:
        summary = " … ".join(by_url[url][:_MAX_FACTS_PER_SOURCE])[:_MAX_SUMMARY_CHARS]
        resources.append(Resource(source_url=url, title=_host(url), summary=summary))
    return resources
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_research_store.py -q`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/letter/research_store.py tests/test_research_store.py
git commit -m "feat: research_store groups a bundle into per-source resources"
```

---

### Task 2: `company_resources` table + CRUD in db.py

**Files:**
- Modify: `src/job_dashboard/db.py` (add table + functions; wire `_ensure_company_resources_table` into `init_db` next to `_ensure_cover_letters_table`)
- Test: `tests/test_company_resources_db.py`

**Interfaces:**
- Produces:
  - `company_key(company: str) -> str`
  - `upsert_company_resources(conn, company_key: str, resources: list[dict]) -> int` — each dict `{source_url, title, summary}`; INSERT new, UPDATE title/summary on `(company_key, source_url)` conflict, PRESERVE `selected`. Returns rows written.
  - `company_resources_for(conn, company_key: str) -> list[dict]` — newest-first; each dict `{id, company_key, source_url, title, summary, selected(bool), created_at}`.
  - `set_selected_resources(conn, company_key: str, source_urls: list[str]) -> None` — clears the company's selection, sets `selected=1` for up to the first 2 given urls that exist for the company.
  - `selected_resources_for(conn, company_key: str) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_company_resources_db.py
from job_dashboard.db import (
    init_db, company_key, upsert_company_resources, company_resources_for,
    set_selected_resources, selected_resources_for,
)


def _conn(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _r(u, t="host", s="summary"):
    return {"source_url": u, "title": t, "summary": s}


def test_company_key_normalizes_variants_together():
    assert company_key("JPMorganChase") == company_key("  jpmorganchase  ")
    assert company_key("Acme Inc") == company_key("Acme")


def test_upsert_then_list_roundtrip(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r("https://a.com/1"), _r("https://a.com/2")])
    rows = company_resources_for(c, ck)
    assert {r["source_url"] for r in rows} == {"https://a.com/1", "https://a.com/2"}
    assert all(r["selected"] is False for r in rows)


def test_upsert_refreshes_summary_but_preserves_selection(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r("https://a.com/1", s="old")])
    set_selected_resources(c, ck, ["https://a.com/1"])
    upsert_company_resources(c, ck, [_r("https://a.com/1", s="new summary")])
    rows = company_resources_for(c, ck)
    assert len(rows) == 1
    assert rows[0]["summary"] == "new summary"
    assert rows[0]["selected"] is True  # selection survived the refresh


def test_select_caps_at_two_and_clears_prior(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r(f"https://a.com/{i}") for i in range(4)])
    set_selected_resources(c, ck, ["https://a.com/0", "https://a.com/1", "https://a.com/2"])
    sel = selected_resources_for(c, ck)
    assert len(sel) == 2  # capped
    set_selected_resources(c, ck, ["https://a.com/3"])
    sel = selected_resources_for(c, ck)
    assert [r["source_url"] for r in sel] == ["https://a.com/3"]  # prior cleared


def test_unknown_company_yields_empty(tmp_path):
    assert company_resources_for(_conn(tmp_path), company_key("Nobody")) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_company_resources_db.py -q`
Expected: FAIL (functions missing).

- [ ] **Step 3: Implement in db.py**

Add near the other `_ensure_*` helpers, and add `_ensure_company_resources_table(conn)` to `init_db` right after `_ensure_cover_letters_table(conn)`.

```python
import re  # if not already imported at top of db.py

_COMPANY_SUFFIX_RE = re.compile(r"\b(inc|llc|ltd|corp|co)\.?$")


def company_key(company):
    key = " ".join((company or "").split()).strip().lower()
    return _COMPANY_SUFFIX_RE.sub("", key).strip()


def _ensure_company_resources_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_key TEXT NOT NULL,
            source_url TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            selected INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE (company_key, source_url)
        )
    """)


def upsert_company_resources(conn, company_key, resources):
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in resources:
        conn.execute(
            """INSERT INTO company_resources
                   (company_key, source_url, title, summary, selected, created_at)
               VALUES (?, ?, ?, ?, 0, ?)
               ON CONFLICT(company_key, source_url)
               DO UPDATE SET title=excluded.title, summary=excluded.summary""",
            (company_key, r["source_url"], r.get("title"), r.get("summary"), now),
        )
        n += 1
    conn.commit()
    return n


def _resource_rows(conn, company_key, selected_only=False):
    q = ("SELECT id, company_key, source_url, title, summary, selected, created_at "
         "FROM company_resources WHERE company_key = ?")
    if selected_only:
        q += " AND selected = 1"
    q += " ORDER BY created_at DESC, id DESC"
    keys = ("id", "company_key", "source_url", "title", "summary", "selected", "created_at")
    out = []
    for row in conn.execute(q, (company_key,)).fetchall():
        d = dict(zip(keys, row))
        d["selected"] = bool(d["selected"])
        out.append(d)
    return out


def company_resources_for(conn, company_key):
    return _resource_rows(conn, company_key)


def selected_resources_for(conn, company_key):
    return _resource_rows(conn, company_key, selected_only=True)


def set_selected_resources(conn, company_key, source_urls):
    conn.execute("UPDATE company_resources SET selected = 0 WHERE company_key = ?",
                 (company_key,))
    existing = {r["source_url"] for r in company_resources_for(conn, company_key)}
    chosen = [u for u in source_urls if u in existing][:2]
    for u in chosen:
        conn.execute(
            "UPDATE company_resources SET selected = 1 WHERE company_key = ? AND source_url = ?",
            (company_key, u),
        )
    conn.commit()
```

Confirm `datetime`, `timezone`, `re` are imported at the top of db.py (add any missing).

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_company_resources_db.py -q`
Expected: PASS (5). Then `python3 -m pytest -q` (full suite green).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/db.py tests/test_company_resources_db.py
git commit -m "feat: company_resources table (per-company curated sources) + CRUD"
```

---

### Task 3: API — gather/list/select endpoints + draft grounds in selected

**Files:**
- Modify: `src/job_dashboard/api/app.py` (DefaultLetterEngine methods + 3 routes; change `draft` to use selected resources)
- Test: `tests/test_company_resources_api.py`; extend the fake engine in `tests/test_cover_letter_api.py` if it lacks the new methods.

**Interfaces:**
- Consumes: `research_store.resources_from_bundle`; db `company_key`, `upsert_company_resources`, `company_resources_for`, `set_selected_resources`, `selected_resources_for`; `company_research`, `draft_cover_letter`, `check_grounding`, `Fact`, `ResearchBundle`.
- Produces routes:
  - `POST /api/jobs/{id}/company-research` → `{company, resources:[{source_url,title,summary,selected}]}`
  - `GET /api/jobs/{id}/company-resources` → `{company, resources:[...]}`
  - `POST /api/jobs/{id}/company-resources/select` body `{source_urls:[...]}` → `{company, resources:[...]}`
  - `DefaultLetterEngine`: `gather_resources(detail)`, `list_resources(detail)`, `select_resources(detail, source_urls)`; `draft(detail)` now grounds in selected (fallback top-2, then fresh research).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_company_resources_api.py
from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing  # the dataclass insert_job expects


def _seed_job(db):
    conn = init_db(db)
    insert_job(conn, JobListing(source="s", title="Data Scientist", company="Acme",
                                job_url="https://x.com/1", description="fraud ML role"))
    jid = conn.execute("SELECT id FROM jobs ORDER BY id LIMIT 1").fetchone()[0]
    conn.close()
    return jid


class FakeEngine:
    def __init__(self, db_path):
        self.db_path = db_path
    def gather_resources(self, detail):
        return {"company": detail.get("company"), "resources": [
            {"source_url": "https://acme.com/acs", "title": "acme.com",
             "summary": "Account Confidence Score, an AI/ML fraud score.", "selected": False},
            {"source_url": "https://blog.acme.com/mesh", "title": "blog.acme.com",
             "summary": "Built a data mesh.", "selected": False},
        ]}
    def list_resources(self, detail):
        return {"company": detail.get("company"), "resources": []}
    def select_resources(self, detail, source_urls):
        return {"company": detail.get("company"),
                "resources": [{"source_url": u, "title": "t", "summary": "s",
                               "selected": True} for u in source_urls[:2]]}
    def draft(self, detail):
        return {"body": "Dear Hiring Manager, ...", "company_facts_used": [],
                "flags": [], "grounding": {"unsupported_company_claims": []}}
    def generate(self, job_id, body):
        return {"cover_letter_id": 1, "pdf_url": "/api/cover-letters/1/pdf"}


def test_gather_list_select_flow(tmp_path):
    db = str(tmp_path / "t.db")
    jid = _seed_job(db)
    c = TestClient(create_app(db_path=db, letter_engine=FakeEngine(db)))
    r = c.post(f"/api/jobs/{jid}/company-research")
    assert r.status_code == 200
    assert len(r.json()["resources"]) == 2
    r = c.post(f"/api/jobs/{jid}/company-resources/select",
               json={"source_urls": ["https://acme.com/acs"]})
    assert r.status_code == 200
    assert r.json()["resources"][0]["selected"] is True
    assert c.get(f"/api/jobs/{jid}/company-resources").status_code == 200


def test_unknown_job_404(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db)
    c = TestClient(create_app(db_path=db, letter_engine=FakeEngine(db)))
    assert c.post("/api/jobs/999999/company-research").status_code == 404
    assert c.post("/api/jobs/999999/company-resources/select",
                  json={"source_urls": []}).status_code == 404
```

Note: `insert_job`/`JobListing` is the real seeding path (see `tests/test_cover_letter_api.py`). Confirm `JobListing`'s import path (grep `class JobListing`). The existing `FakeLetterEngine` in `test_cover_letter_api.py` needs the 3 new methods ONLY if a shared test hits the new routes — it doesn't, so leave it unless a test fails.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_company_resources_api.py -q`
Expected: FAIL (routes 404 / engine methods missing).

- [ ] **Step 3: Implement in app.py**

Add to `DefaultLetterEngine` (mirrors how `generate` opens `init_db(self.db_path)`):

```python
def _company_key(self, detail):
    from job_dashboard.db import company_key
    return company_key(detail.get("company") or "")

def gather_resources(self, detail):
    from job_dashboard.db import init_db, upsert_company_resources, company_resources_for
    from job_dashboard.letter.research_store import resources_from_bundle
    bundle = self._research_bundle(detail)  # existing helper: company_research(...)
    ck = self._company_key(detail)
    conn = init_db(self.db_path)
    try:
        upsert_company_resources(conn, ck, [
            {"source_url": r.source_url, "title": r.title, "summary": r.summary}
            for r in resources_from_bundle(bundle)
        ])
        rows = company_resources_for(conn, ck)
    finally:
        conn.close()
    return {"company": detail.get("company"), "resources": _public_resources(rows)}

def list_resources(self, detail):
    from job_dashboard.db import init_db, company_resources_for
    conn = init_db(self.db_path)
    try:
        rows = company_resources_for(conn, self._company_key(detail))
    finally:
        conn.close()
    return {"company": detail.get("company"), "resources": _public_resources(rows)}

def select_resources(self, detail, source_urls):
    from job_dashboard.db import init_db, set_selected_resources, company_resources_for
    ck = self._company_key(detail)
    conn = init_db(self.db_path)
    try:
        set_selected_resources(conn, ck, source_urls or [])
        rows = company_resources_for(conn, ck)
    finally:
        conn.close()
    return {"company": detail.get("company"), "resources": _public_resources(rows)}
```

Add a module-level helper near `DefaultLetterEngine`:

```python
def _public_resources(rows):
    return [{"source_url": r["source_url"], "title": r["title"],
             "summary": r["summary"], "selected": r["selected"]} for r in rows]
```

Change `DefaultLetterEngine.draft` to ground in selected resources:

```python
def draft(self, detail):
    from job_dashboard.db import init_db, selected_resources_for, company_resources_for
    from job_dashboard.letter.company_research import Fact, ResearchBundle
    ck = self._company_key(detail)
    conn = init_db(self.db_path)
    try:
        chosen = selected_resources_for(conn, ck) or company_resources_for(conn, ck)[:2]
    finally:
        conn.close()
    if chosen:
        bundle = ResearchBundle(
            facts=[Fact(text=r["summary"], source_url=r["source_url"]) for r in chosen],
            queries_used=[], empty=False)
    else:
        bundle = self._research_bundle(detail)   # today's fresh research fallback
    try:
        profile_text = compose_profile_text().text
    except Exception:
        profile_text = ""
    result = draft_cover_letter(detail, profile_text, bundle)
    job_text = " ".join(str(detail.get(k) or "") for k in ("title", "company", "description"))
    grounding = check_grounding(result["body"], bundle, profile_text, job_text)
    return {"body": result["body"], "company_facts_used": result["company_facts_used"],
            "flags": result["flags"],
            "grounding": {"unsupported_company_claims": grounding.unsupported_company_claims}}
```

Add the 3 routes near the other cover-letter routes (all resolve the job via the existing `job_detail`, 404 if missing):

```python
class ResourceSelectRequest(BaseModel):
    source_urls: list[str] = []

@app.post("/api/jobs/{job_id}/company-research")
def gather_company_research(job_id: int):
    with db() as conn:
        detail = job_detail(conn, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return engine.gather_resources(detail)

@app.get("/api/jobs/{job_id}/company-resources")
def get_company_resources(job_id: int):
    with db() as conn:
        detail = job_detail(conn, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return engine.list_resources(detail)

@app.post("/api/jobs/{job_id}/company-resources/select")
def select_company_resources(job_id: int, body: ResourceSelectRequest):
    with db() as conn:
        detail = job_detail(conn, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return engine.select_resources(detail, body.source_urls)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_company_resources_api.py tests/test_cover_letter_api.py -q`
Expected: PASS. Then `python3 -m pytest -q` full suite green (if the real-engine draft test in test_cover_letter_api.py now reads resources, it still returns 200 with no rows → fresh-research fallback; keep it green).

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/api/app.py tests/test_company_resources_api.py
git commit -m "feat: company-research gather/list/select API + draft grounds in selected resources"
```

---

### Task 4: `CoverLetterPanel` curation step + api.js

**Files:**
- Modify: `frontend/src/api.js` (3 functions), `frontend/src/components/CoverLetterPanel.jsx`
- Test: `frontend/src/__tests__/cover_letter_panel.test.jsx` (extend)

**Interfaces:**
- `api.js` adds: `gatherCompanyResources(jobId)` (POST company-research → unwrap to `resources`), `fetchCompanyResources(jobId)` (GET → unwrap `resources`), `selectCompanyResources(jobId, sourceUrls)` (POST select `{source_urls}` → unwrap `resources`). Match existing api.js base-url/error style and envelope-unwrap habit.
- `CoverLetterPanel`: a research step before draft. "Find company research" → cards (title, summary, source link `_blank rel=noopener`, checkbox). Checking calls `selectCompanyResources` (max 2; block a 3rd with a hint). Then existing "Draft cover letter" → existing flow.

- [ ] **Step 1: Write the failing tests** (mock `global.fetch` with the exact shapes)

```jsx
// add to frontend/src/__tests__/cover_letter_panel.test.jsx
const RESOURCES = {
  company: "Acme",
  resources: [
    { source_url: "https://acme.com/acs", title: "acme.com",
      summary: "Account Confidence Score, an AI/ML fraud score.", selected: false },
    { source_url: "https://blog.acme.com/mesh", title: "blog.acme.com",
      summary: "Built a data mesh.", selected: false },
  ],
};

test("gathers and renders company resource cards with source links", async () => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/company-research"))
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(RESOURCES) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resources: [] }) });
  });
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Find company research/));
  await waitFor(() => expect(screen.getByText(/Account Confidence Score/)).toBeDefined());
  const link = screen.getByRole("link", { name: /acme\.com/ });
  expect(link.href).toContain("acme.com/acs");
  expect(link.target).toBe("_blank");
});

test("selecting more than two sources is prevented", async () => {
  // gather returns 3 resources; check all three; the 3rd check does not persist
  // assert selectCompanyResources was called with at most 2 urls (inspect fetch body)
});

test("no send/apply/email control exists in the research step", async () => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(RESOURCES) }));
  render(<CoverLetterPanel jobId={1} />);
  fireEvent.click(screen.getByText(/Find company research/));
  await waitFor(() => screen.getByText(/data mesh/));
  expect(screen.queryByText(/send/i)).toBeNull();
  expect(screen.queryByText(/apply/i)).toBeNull();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- cover_letter_panel` (from `frontend/`)
Expected: FAIL (button/cards missing).

- [ ] **Step 3: Implement** `gatherCompanyResources`/`fetchCompanyResources`/`selectCompanyResources` in api.js, and a research stage in `CoverLetterPanel`: an idle "Find company research" button → gather → render cards (title, summary, source `<a target=_blank rel="noopener noreferrer">`, checkbox). Track `selectedUrls` (≤2; ignore a 3rd, show a muted "pick up to 2" hint). Each toggle calls `selectCompanyResources(jobId, nextUrls)`. Keep the existing "Draft cover letter" button and all downstream stages unchanged (Teal v2 tokens, reduced-motion, NO send/apply control).

- [ ] **Step 4: Run to verify it passes**

Run: `npm test` (all vitest green), then `npm run build` (must succeed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/components/CoverLetterPanel.jsx frontend/src/__tests__/cover_letter_panel.test.jsx
git commit -m "feat: company-research curation step in CoverLetterPanel (pick up to 2 sources)"
```

---

### Task 5: live end-to-end (controller-driven, not a subagent)

- [ ] With `TINYFISH_API_KEY` set + Ollama up: start the server (`serve:app`), open the browser to a real company's job → "Find company research" → confirm ~6 source cards with real summaries + working source links → pick 2 → "Draft cover letter" → confirm the draft grounds in EXACTLY those two sources (their URLs appear as inline citations / in `company_facts_used`) → Generate → real PDF. Screenshot.
- [ ] Re-open a different job at the same company → confirm the saved resources + the 2 picks persist (reused). Ledger the result.
- [ ] Then: whole-branch review + finishing-a-development-branch.

## Not covered (spec non-goals)

Manual URL paste; editing a resource summary in the UI; a standalone research-manager page; cross-company ranking/tagging/expiry; auto-send (Application Agent).
