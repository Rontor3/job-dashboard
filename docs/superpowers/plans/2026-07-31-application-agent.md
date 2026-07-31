# Application Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Dispatch prompts in caveman style (project memory).

**Goal:** Build the app-side of the Application Agent — store the user's reusable application profile, assemble a per-job answer package (resume + optional cover letter), draft grounded screening answers, track applications — plus a runbook the browser agent follows to auto-fill the form in the user's Chrome and STOP at Submit.

**Architecture:** New `src/job_dashboard/apply/` package: `store.py` (application_profile + applications tables/CRUD, wired into `init_db`), `package.py` (assemble), `screening.py` (grounded qwen answer, reuses the cover-letter Ollama seam), `ats_maps.py` + `ats_maps/*.json` (field-map data). Endpoints live in a new `api/apply_routes.py` APIRouter included by `create_app` (keeps the over-cap `app.py`/`db.py` from growing). A React `ApplyPanel`. Side B (the browser fill) is a documented runbook, not code.

**Tech Stack:** Python 3.11+, sqlite3, FastAPI (APIRouter), Ollama qwen2.5:14b (reused), pytest (fakes — no browser/LLM), React + Vitest. Claude-in-Chrome for the live fill (manual).

## Global Constraints

- **SAFETY RAILS (every task inherits):** the agent NEVER clicks Submit/apply/confirm; never enters passwords, creates accounts, or solves CAPTCHAs; fills ONLY from saved `application_profile` + the job's resume/letter/screening drafts, leaving any unmappable field blank + flagged; leaves EEO/demographic untouched; acts only on the user-given job URL; two review gates (approve package in-app, final on-page review before the user submits). These live in the runbook (Side B) and the panel copy (Side A).
- **Cover letter is OPTIONAL:** `applications.cover_letter_id` is nullable; package assembly never requires one; resume-only is valid.
- Screening answers follow the never-fabricate discipline (grounded in profile/research/resume; best-effort + human edit); llm failure → truthful general answer, never raises, never 500.
- New tables go in `apply/store.py` (NOT db.py) to respect the 500-line cap; `init_db` calls `apply.store.ensure_application_tables(conn)`.
- Apply endpoints go in `api/apply_routes.py` (APIRouter), included by `create_app`; injectable fakes so no test hits a browser/LLM/network.
- Existing suite (241 pytest + 41 vitest) stays green.

---

### Task 1: `apply/store.py` — profile + applications tables & CRUD

**Files:**
- Create: `src/job_dashboard/apply/__init__.py` (empty), `src/job_dashboard/apply/store.py`
- Modify: `src/job_dashboard/db.py` (`init_db` calls `ensure_application_tables`)
- Test: `tests/test_apply_store.py`

**Interfaces (Produces):**
- `ensure_application_tables(conn)` — idempotent create of both tables.
- `get_application_profile(conn) -> dict | None` (single row id=1).
- `save_application_profile(conn, fields: dict) -> dict` (upsert row id=1, returns saved).
- `save_application(conn, job_id, resume_id=None, cover_letter_id=None, screening=None, ats=None, status="prepared") -> int`.
- `get_application(conn, job_id) -> dict | None` (latest for the job; `screening` json-decoded to list; `cover_letter_id` may be None).
- `set_application_status(conn, application_id, status, applied_at=None) -> None`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apply_store.py
from job_dashboard.db import init_db
from job_dashboard.apply.store import (
    get_application_profile, save_application_profile,
    save_application, get_application, set_application_status,
)


def _conn(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_profile_unset_is_none_then_roundtrips(tmp_path):
    c = _conn(tmp_path)
    assert get_application_profile(c) is None
    saved = save_application_profile(c, {
        "full_name": "Rakshit Singh", "email": "r@x.com", "phone": "123",
        "work_authorization": "US: needs sponsorship, no H1B", "willing_to_relocate": True,
    })
    assert saved["full_name"] == "Rakshit Singh"
    got = get_application_profile(c)
    assert got["email"] == "r@x.com" and got["willing_to_relocate"] in (True, 1)


def test_profile_upsert_updates_single_row(tmp_path):
    c = _conn(tmp_path)
    save_application_profile(c, {"full_name": "A", "email": "a@x.com"})
    save_application_profile(c, {"full_name": "B", "email": "b@x.com"})
    got = get_application_profile(c)
    assert got["full_name"] == "B"  # still one row, updated


def test_application_roundtrip_cover_letter_optional(tmp_path):
    c = _conn(tmp_path)
    aid = save_application(c, job_id=7, resume_id=3, cover_letter_id=None,
                           screening=[{"question": "Why us?", "answer": "Because X"}],
                           ats="greenhouse", status="prepared")
    got = get_application(c, 7)
    assert got["id"] == aid and got["cover_letter_id"] is None
    assert got["resume_id"] == 3 and got["ats"] == "greenhouse"
    assert got["screening"][0]["question"] == "Why us?"
    set_application_status(c, aid, "applied", applied_at="2026-07-31T00:00:00Z")
    assert get_application(c, 7)["status"] == "applied"


def test_get_application_unknown_job_is_none(tmp_path):
    assert get_application(_conn(tmp_path), 999) is None
```

- [ ] **Step 2: Run → FAIL.** `python3 -m pytest tests/test_apply_store.py -q`

- [ ] **Step 3: Implement `apply/store.py`**

```python
"""Storage for the Application Agent: the reusable application_profile
(single row) and per-job applications. Kept out of db.py to respect the
500-line cap; init_db calls ensure_application_tables.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

_PROFILE_COLS = (
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "willing_to_relocate", "notice_period", "salary_expectation",
)


def ensure_application_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            full_name TEXT, email TEXT, phone TEXT, location TEXT,
            linkedin_url TEXT, github_url TEXT, portfolio_url TEXT,
            work_authorization TEXT, years_experience TEXT,
            willing_to_relocate INTEGER, notice_period TEXT,
            salary_expectation TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            resume_id INTEGER, cover_letter_id INTEGER,
            status TEXT NOT NULL DEFAULT 'prepared',
            screening TEXT, ats TEXT,
            applied_at TEXT, created_at TEXT NOT NULL
        )
    """)


def get_application_profile(conn):
    row = conn.execute(
        "SELECT " + ", ".join(_PROFILE_COLS) + ", updated_at "
        "FROM application_profile WHERE id = 1").fetchone()
    if row is None:
        return None
    d = dict(zip(_PROFILE_COLS + ("updated_at",), row))
    d["willing_to_relocate"] = bool(d["willing_to_relocate"]) if d["willing_to_relocate"] is not None else None
    return d


def save_application_profile(conn, fields):
    now = datetime.now(timezone.utc).isoformat()
    vals = {k: fields.get(k) for k in _PROFILE_COLS}
    if vals.get("willing_to_relocate") is not None:
        vals["willing_to_relocate"] = 1 if vals["willing_to_relocate"] else 0
    cols = list(_PROFILE_COLS)
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    conn.execute(
        f"INSERT INTO application_profile (id, {', '.join(cols)}, updated_at) "
        f"VALUES (1, {', '.join(['?'] * len(cols))}, ?) "
        f"ON CONFLICT(id) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols) + ", updated_at=excluded.updated_at",
        tuple(vals[c] for c in cols) + (now,),
    )
    conn.commit()
    return get_application_profile(conn)


def save_application(conn, job_id, resume_id=None, cover_letter_id=None,
                     screening=None, ats=None, status="prepared"):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO applications
               (job_id, resume_id, cover_letter_id, status, screening, ats, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (job_id, resume_id, cover_letter_id, status,
         json.dumps(screening or []), ats, now),
    )
    conn.commit()
    return conn.execute("SELECT id FROM applications ORDER BY id DESC LIMIT 1").fetchone()[0]


def get_application(conn, job_id):
    row = conn.execute(
        """SELECT id, job_id, resume_id, cover_letter_id, status, screening, ats,
                  applied_at, created_at
           FROM applications WHERE job_id = ? ORDER BY id DESC LIMIT 1""",
        (job_id,)).fetchone()
    if row is None:
        return None
    keys = ("id", "job_id", "resume_id", "cover_letter_id", "status", "screening",
            "ats", "applied_at", "created_at")
    d = dict(zip(keys, row))
    d["screening"] = json.loads(d["screening"]) if d["screening"] else []
    return d


def set_application_status(conn, application_id, status, applied_at=None):
    conn.execute("UPDATE applications SET status = ?, applied_at = ? WHERE id = ?",
                 (status, applied_at, application_id))
    conn.commit()
```

Wire into `db.py` `init_db` (after the other `_ensure_*` calls). Use a LOCAL
import inside `init_db` (not module-top) so db.py — imported very early by many
modules — never risks an import cycle:

```python
    # ... inside init_db, before conn.commit():
    from job_dashboard.apply.store import ensure_application_tables
    ensure_application_tables(conn)
```

- [ ] **Step 4: Run → PASS (4).** Then `python3 -m pytest -q` (full green).
- [ ] **Step 5: Commit** `feat: application_profile + applications tables & CRUD (apply/store.py)`.

---

### Task 2: `apply/package.py` — assemble the per-job package

**Files:** Create `src/job_dashboard/apply/package.py`; Test `tests/test_apply_package.py`.

**Interfaces:** `assemble_application_package(conn, job_id) -> dict` → `{profile, resume, cover_letter, job}` where `profile` is the saved profile (or None), `resume` is the most-recent resume dict for the job (or None), `cover_letter` is the most-recent cover-letter dict (or None — OPTIONAL), `job` is `job_detail`. Uses `get_application_profile`, `resumes_for_job`, `cover_letters_for_job`, `job_detail`. Never raises on missing pieces.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apply_package.py
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from job_dashboard.apply.store import save_application_profile
from job_dashboard.apply.package import assemble_application_package


def _seed(tmp_path):
    c = init_db(str(tmp_path / "t.db"))
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://x/1", description="jd"))
    jid = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    return c, jid


def test_package_resume_only_when_no_cover_letter(tmp_path):
    c, jid = _seed(tmp_path)
    save_application_profile(c, {"full_name": "R", "email": "r@x.com"})
    pkg = assemble_application_package(c, jid)
    assert pkg["profile"]["full_name"] == "R"
    assert pkg["cover_letter"] is None          # optional, absent
    assert pkg["job"]["company"] == "Acme"


def test_package_includes_cover_letter_when_present(tmp_path):
    from job_dashboard.db import save_cover_letter
    c, jid = _seed(tmp_path)
    save_cover_letter(c, jid, "/tmp/cl.pdf", "Dear ...", [])
    pkg = assemble_application_package(c, jid)
    assert pkg["cover_letter"] is not None
    assert pkg["cover_letter"]["pdf_path"] == "/tmp/cl.pdf"


def test_package_tolerates_unset_profile(tmp_path):
    c, jid = _seed(tmp_path)
    pkg = assemble_application_package(c, jid)
    assert pkg["profile"] is None and pkg["job"]["company"] == "Acme"
```

- [ ] **Step 2: FAIL.** **Step 3: Implement**

```python
"""Assemble a per-job application package: profile + most-recent resume +
OPTIONAL most-recent cover letter + job detail. Never requires a letter.
"""
from job_dashboard.db import (
    cover_letters_for_job, job_detail, resumes_for_job,
)
from job_dashboard.apply.store import get_application_profile


def assemble_application_package(conn, job_id):
    resumes = resumes_for_job(conn, job_id) or []
    letters = cover_letters_for_job(conn, job_id) or []
    return {
        "profile": get_application_profile(conn),
        "resume": resumes[0] if resumes else None,
        "cover_letter": letters[0] if letters else None,  # OPTIONAL
        "job": job_detail(conn, job_id),
    }
```

- [ ] **Step 4: PASS (3); full suite green. Step 5: Commit** `feat: assemble_application_package (resume + optional cover letter)`.

---

### Task 3: `apply/ats_maps` — field-map data + loader/detect

**Files:** Create `src/job_dashboard/apply/ats_maps.py`, `src/job_dashboard/apply/ats_maps/{greenhouse,lever,ashby,workday,generic}.json`; Test `tests/test_ats_maps.py`.

**Interfaces:** `load_ats_map(name) -> dict` (raises `KeyError`/`FileNotFoundError` on unknown — API turns into 404); `detect_ats(url) -> str` (returns one of the known names or `"generic"`); `KNOWN_ATS: tuple`. Each map: `{intent: [label synonyms]}` covering at least `full_name, email, phone, location, linkedin, github, resume, cover_letter`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ats_maps.py
import pytest
from job_dashboard.apply.ats_maps import load_ats_map, detect_ats, KNOWN_ATS

REQUIRED = {"full_name", "email", "phone", "resume", "cover_letter"}


@pytest.mark.parametrize("name", ["greenhouse", "lever", "ashby", "workday", "generic"])
def test_each_map_loads_and_has_required_intents(name):
    m = load_ats_map(name)
    assert REQUIRED.issubset(m.keys())
    assert all(isinstance(v, list) and v for v in m.values())


def test_detect_ats_from_urls():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/xyz") == "ashby"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/en-US/x") == "workday"
    assert detect_ats("https://careers.acme.com/apply") == "generic"


def test_load_unknown_raises():
    with pytest.raises((KeyError, FileNotFoundError)):
        load_ats_map("nosuch")
```

- [ ] **Step 2: FAIL. Step 3: Implement** the 5 JSON files (real label synonyms per platform) and:

```python
# src/job_dashboard/apply/ats_maps.py
import json
from pathlib import Path

_DIR = Path(__file__).parent / "ats_maps"
KNOWN_ATS = ("greenhouse", "lever", "ashby", "workday")
_DETECT = {"greenhouse.io": "greenhouse", "lever.co": "lever",
           "ashbyhq.com": "ashby", "myworkdayjobs.com": "workday", "workday": "workday"}


def load_ats_map(name):
    path = _DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(name)
    return json.loads(path.read_text())


def detect_ats(url):
    u = (url or "").lower()
    for needle, name in _DETECT.items():
        if needle in u:
            return name
    return "generic"
```

Example `greenhouse.json` (mirror shape for the others with each platform's labels):
```json
{
  "full_name": ["Full Name", "First Name", "Last Name", "Name"],
  "email": ["Email", "Email Address"],
  "phone": ["Phone", "Phone Number", "Mobile"],
  "location": ["Location", "City", "Current Location"],
  "linkedin": ["LinkedIn Profile", "LinkedIn", "LinkedIn URL"],
  "github": ["GitHub", "GitHub URL", "Website"],
  "resume": ["Resume/CV", "Attach Resume", "Resume"],
  "cover_letter": ["Cover Letter"]
}
```

- [ ] **Step 4: PASS; full suite green. Step 5: Commit** `feat: ATS field-maps (greenhouse/lever/ashby/workday/generic) + detect`.

---

### Task 4: `apply/screening.py` — grounded screening answer

**Files:** Create `src/job_dashboard/apply/screening.py`; Test `tests/test_apply_screening.py`.

**Interfaces:** `draft_screening_answer(job, question, profile_text, research, resume_text="", llm=None) -> {answer, flags}`. Reuses `letter.draft.make_default_llm` (Ollama seam). Grounds strictly in profile/research/resume; empty/uncertain → truthful general answer with no fabricated company specifics; ANY llm failure → general truthful answer (never raises). `research` is a `ResearchBundle` (may be empty).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_apply_screening.py
from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.apply.screening import draft_screening_answer

JOB = {"title": "ML Engineer", "company": "Acme", "description": "fraud ML"}


def test_uses_fake_llm_answer():
    out = draft_screening_answer(JOB, "Why Acme?", "I built fraud models.",
                                 ResearchBundle([Fact("Acme cut fraud 40%", "http://a")], [], False),
                                 resume_text="fraud pipeline", llm=lambda p: "Because Acme cut fraud 40%.")
    assert "answer" in out and out["answer"]


def test_llm_raise_falls_back_no_raise():
    def boom(p): raise RuntimeError("ollama down")
    out = draft_screening_answer(JOB, "Why us?", "profile", ResearchBundle([], [], True),
                                 llm=boom)
    assert isinstance(out["answer"], str)   # general truthful answer, no raise


def test_empty_research_no_fabricated_company_specifics():
    # with empty research + a fake llm that would echo a company fact, the prompt
    # must not have supplied one; assert a known fabricated token is absent.
    out = draft_screening_answer(JOB, "Why us?", "profile", ResearchBundle([], [], True),
                                 llm=lambda p: "I admire your work." if "FAKEPROD" not in p else "FAKEPROD")
    assert "FAKEPROD" not in out["answer"]
```

- [ ] **Step 2: FAIL. Step 3: Implement** — build a grounded prompt (question + profile + resume + `research.facts` only, "answer truthfully in 3-5 sentences, use a company specific only if in the facts, never invent"); default llm = `make_default_llm()`; wrap the call so any exception / empty → a general truthful answer assembled from profile (no company specifics). Return `{answer, flags}` (`flags` lists e.g. `"general_fallback"` when llm unavailable).
- [ ] **Step 4: PASS. Step 5: live smoke skipif Ollama down** (real qwen answer to "Why {company}?"). **Commit** `feat: grounded screening-answer drafting (qwen, reuses cover-letter seam)`.

---

### Task 5: API — apply routes (profile/package/screening/ats-map/application)

**Files:** Create `src/job_dashboard/api/apply_routes.py`; Modify `src/job_dashboard/api/app.py` (`create_app` gains `screening_engine=None` and `app.include_router(build_apply_router(db_path, screening_engine))`); Test `tests/test_apply_api.py`.

**Interfaces (routes):**
- `GET /api/application-profile` → profile or `{}`; `PUT /api/application-profile` `{fields}` → saved profile.
- `GET /api/jobs/{id}/application-package` → `{profile, resume, cover_letter, job, ats_hint}` (ats_hint from `detect_ats(job.job_url)`). 404 unknown job.
- `POST /api/jobs/{id}/screening-answer` `{question}` → `{answer, flags}` (grounds via selected company resources → bundle, like the draft; Ollama down → general answer, never 500).
- `GET /api/ats-map/{name}` → map json; 404 unknown.
- `POST /api/jobs/{id}/application` `{resume_id?, cover_letter_id?, screening?, ats?, status}` → `{application_id, status}`; `GET /api/jobs/{id}/application` → record or `{}`.
- `build_apply_router(db_path, screening_engine=None) -> APIRouter`. `screening_engine` default wraps `draft_screening_answer` + a research bundle from `selected_resources_for` (fallback fresh `company_research`); tests inject a fake.

- [ ] **Step 1: Write failing tests** (TestClient + fake screening_engine; seed jobs via `insert_job`/`JobListing`):

```python
# tests/test_apply_api.py
from fastapi.testclient import TestClient
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing
from job_dashboard.api.app import create_app


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    c = init_db(db)
    insert_job(c, JobListing(source="s", title="ML Eng", company="Acme",
                             job_url="https://boards.greenhouse.io/acme/jobs/1", description="jd"))
    jid = c.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    c.close()

    class FakeScreening:
        def answer(self, detail, question):
            return {"answer": f"Because {detail.get('company')} is great.", "flags": []}
    return TestClient(create_app(db_path=db, screening_engine=FakeScreening())), jid


def test_profile_put_then_get(tmp_path):
    c, _ = _client(tmp_path)
    r = c.put("/api/application-profile", json={"full_name": "R", "email": "r@x.com"})
    assert r.status_code == 200 and r.json()["full_name"] == "R"
    assert c.get("/api/application-profile").json()["email"] == "r@x.com"


def test_package_has_optional_cover_letter_and_ats_hint(tmp_path):
    c, jid = _client(tmp_path)
    r = c.get(f"/api/jobs/{jid}/application-package")
    assert r.status_code == 200
    body = r.json()
    assert body["cover_letter"] is None and body["ats_hint"] == "greenhouse"


def test_screening_answer_shape(tmp_path):
    c, jid = _client(tmp_path)
    r = c.post(f"/api/jobs/{jid}/screening-answer", json={"question": "Why us?"})
    assert r.status_code == 200 and "answer" in r.json()


def test_application_create_then_get_roundtrip(tmp_path):
    c, jid = _client(tmp_path)
    r = c.post(f"/api/jobs/{jid}/application",
               json={"resume_id": None, "cover_letter_id": None,
                     "screening": [{"question": "Q", "answer": "A"}],
                     "ats": "greenhouse", "status": "applied"})
    assert r.status_code == 200
    got = c.get(f"/api/jobs/{jid}/application").json()
    assert got["status"] == "applied" and got["cover_letter_id"] is None


def test_ats_map_route_and_404s(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/ats-map/greenhouse").status_code == 200
    assert c.get("/api/ats-map/nosuch").status_code == 404
    assert c.get("/api/jobs/99999/application-package").status_code == 404
```

- [ ] **Step 2: FAIL. Step 3: Implement** `apply_routes.py` (an `APIRouter`; each handler opens `init_db(db_path)`; the default `screening_engine` builds `profile_text` via `compose_profile_text`, a research bundle from `selected_resources_for` for the job's company (fallback `company_research`), the resume text if available, and calls `draft_screening_answer`; graceful on any failure → general answer). Wire `create_app` to add `screening_engine=None` and `app.include_router(...)`.
- [ ] **Step 4: PASS; full suite green. Step 5: Commit** `feat: application-agent API (profile/package/screening/ats-map/application)`.

---

### Task 6: `ApplyPanel` — review package, safety banner, mark applied

**Files:** Create `frontend/src/components/ApplyPanel.jsx`; Modify `frontend/src/api.js`, `frontend/src/components/JobDetail.jsx`; Test `frontend/src/__tests__/apply_panel.test.jsx`.

**Interfaces:** `api.js` adds `fetchApplicationProfile()`, `saveApplicationProfile(fields)`, `fetchApplicationPackage(jobId)`, `saveApplication(jobId, body)`, `fetchApplication(jobId)`. `<ApplyPanel jobId />` in the detail: shows the package (profile summary, resume to use, **optional cover-letter toggle** default off), a persistent **safety banner** ("The agent fills the form in your Chrome and STOPS at Submit — you review and send it. It never submits, logs in, or solves CAPTCHAs."), a **"Prepare application"** button (POST application `status:"prepared"`), and after you submit on the site a **"Mark as applied"** button (POST `status:"applied"`). **No submit/auto-apply/send control.** Teal v2 tokens, reduced-motion.

- [ ] **Step 1: Write failing tests** (vitest, mock fetch with the real shapes): package renders with resume + optional-letter toggle (off by default); safety banner text present; "Prepare application" calls saveApplication with status prepared; "Mark as applied" calls with status applied; assert NO element matching /submit/i, /auto.?apply/i present.
- [ ] **Step 2: FAIL. Step 3: Implement** the panel + api.js + mount in JobDetail. **Step 4:** `npm test` green + `npm run build`. **Step 5: Commit** `feat: Apply panel (review package, safety banner, mark-applied; no submit control)`.

---

### Task 7: Runbook + live end-to-end (controller-driven) + finish

- [ ] Write `docs/application-agent-runbook.md` — the Side B procedure (detect ATS → load map → open URL in user's Chrome → map & fill → screening answers via endpoint → **stop at Submit** → report filled/blank/flagged), with the safety rails restated as hard stops.
- [ ] Live e2e (with the user, Claude-in-Chrome): fill `application_profile` in the dashboard; pick a real job on a known ATS; **Prepare application**; open the job URL in the user's Chrome; fill mapped fields + resume + (if a slot) cover letter + a grounded screening answer the user edits; **STOP at Submit**; report. User reviews + submits; **Mark as applied**; confirm the record + job status. Screenshot.
- [ ] Whole-branch review + finishing-a-development-branch.

## Not covered (spec non-goals)

Auto-submit; login/account/CAPTCHA; bulk apply; recruiter-contact scraping; non-Chrome; editing ATS maps in UI; headless unattended apply.
