# Job Aggregation (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull job listings from six free sources (JobSpy-covered boards, three free-API remote boards, one RSS board, and the recently-funded-startups sheet) into one deduplicated SQLite database, with full JD text on every listing.

**Architecture:** A `job_dashboard` Python package with one module per source, each returning plain `JobListing`/`Company` dataclasses (no source-specific shape leaks past its own module). `ingest.py` orchestrates calling every source and writing through `db.py`, which owns the SQLite schema and is the only code that touches SQL. Every source module is tested with mocked HTTP/library calls — no test hits the real network.

**Tech Stack:** Python 3.11+, `sqlite3` (stdlib), `requests`, `feedparser`, `python-jobspy`, `pytest`.

## Global Constraints

- Every `JobListing` must carry full job description text (not a title/snippet) — this is required by the semantic matching design in the spec, even though matching itself is a later plan.
- No test may perform a real network call — all HTTP/library calls are mocked via `monkeypatch`.
- `job_url` is the dedup key for jobs; `name` is the dedup key for companies. Never insert a duplicate job; never overwrite a company's `contact_email`/`contact_source` once set (reserved for the later Outreach plan).
- This plan covers **Phase 1 sources only**: JobSpy-backed boards (Indeed, LinkedIn, Naukri, Glassdoor, Google Jobs, ZipRecruiter, Bayt, BDJobs), Remotive, RemoteOK, We Work Remotely, Himalayas, and the startup funding sheet. Scrapling-based sources (Wellfound, jobs24x, unlistedjobs, remotejobs.io) and agent-reach (24h social-signal monitoring) are out of scope for this plan — they need their own follow-up plan since Scrapling setup and agent-reach integration are a different shape of work. Matching/ranking is also a separate later plan (it needs the Profile subsystem too).

---

## File Structure

```
Job Dashboard/
  requirements.txt
  .gitignore                          (adds data/*.db, __pycache__/, .venv/)
  src/
    job_dashboard/
      __init__.py
      models.py                       # JobListing, Company dataclasses
      db.py                           # schema, init_db, insert_job, job_exists, upsert_company
      sources/
        __init__.py
        jobspy_source.py              # fetch_jobspy_jobs()
        remotive_source.py            # fetch_remotive_jobs()
        remoteok_source.py            # fetch_remoteok_jobs()
        wwr_source.py                 # fetch_wwr_jobs()
        himalayas_source.py           # fetch_himalayas_jobs()
        startup_sheet.py              # fetch_funded_startups()
      ingest.py                       # run_ingest()
  tests/
    conftest.py                       # shared FakeResponse fixture
    test_models.py
    test_db.py
    test_jobspy_source.py
    test_remotive_source.py
    test_remoteok_source.py
    test_wwr_source.py
    test_himalayas_source.py
    test_startup_sheet.py
    test_ingest.py
```

---

### Task 1: Project scaffolding + models.py

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/job_dashboard/__init__.py`
- Create: `src/job_dashboard/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `JobListing(source, title, company, job_url, description, location=None, external_id=None, job_type=None, is_remote=None, salary_text=None, posted_date=None)`
- Produces: `Company(name, funding_amount=None, funding_round=None, sector=None, hq=None, founders=None, source="startup_sheet")`

- [ ] **Step 1: Create the project scaffolding**

```bash
mkdir -p "src/job_dashboard/sources" tests data
touch "src/job_dashboard/__init__.py" "src/job_dashboard/sources/__init__.py"
```

- [ ] **Step 2: Write `requirements.txt`**

```
python-jobspy>=1.1.80
requests>=2.31
feedparser>=6.0
pytest>=8.0
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
data/*.db
documents/
```

- [ ] **Step 4: Write the failing test for `models.py`**

```python
# tests/test_models.py
from job_dashboard.models import JobListing, Company


def test_job_listing_requires_core_fields_and_defaults_optional_ones():
    job = JobListing(
        source="test",
        title="ML Engineer",
        company="Acme",
        job_url="https://example.com/1",
        description="Full JD text",
    )
    assert job.source == "test"
    assert job.location is None
    assert job.job_type is None
    assert job.is_remote is None


def test_company_defaults_source_to_startup_sheet():
    company = Company(name="Acme")
    assert company.name == "Acme"
    assert company.source == "startup_sheet"
    assert company.funding_amount is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard'` (or `ImportError`)

- [ ] **Step 6: Implement `models.py`**

```python
# src/job_dashboard/models.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class JobListing:
    source: str
    title: str
    company: str
    job_url: str
    description: str
    location: Optional[str] = None
    external_id: Optional[str] = None
    job_type: Optional[str] = None
    is_remote: Optional[bool] = None
    salary_text: Optional[str] = None
    posted_date: Optional[str] = None


@dataclass
class Company:
    name: str
    funding_amount: Optional[str] = None
    funding_round: Optional[str] = None
    sector: Optional[str] = None
    hq: Optional[str] = None
    founders: Optional[str] = None
    source: str = "startup_sheet"
```

- [ ] **Step 7: Install the package in editable mode so `job_dashboard` is importable**

```bash
pip install -e .
```

If there's no `pyproject.toml`/`setup.py` yet, create a minimal one first:

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "job-dashboard"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 8: Install requirements and run test to verify it passes**

```bash
pip install -r requirements.txt
pytest tests/test_models.py -v
```
Expected: PASS (2 passed)

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore pyproject.toml src/job_dashboard/__init__.py src/job_dashboard/sources/__init__.py src/job_dashboard/models.py tests/test_models.py
git commit -m "feat: scaffold job_dashboard package with JobListing/Company models"
```

---

### Task 2: SQLite schema + `db.py`

**Files:**
- Create: `src/job_dashboard/db.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: `JobListing`, `Company` from `job_dashboard.models`
- Produces: `init_db(path) -> sqlite3.Connection`, `job_exists(conn, job_url) -> bool`, `insert_job(conn, job: JobListing) -> bool` (True if newly inserted), `upsert_company(conn, company: Company) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
from job_dashboard.db import init_db, job_exists, insert_job, upsert_company
from job_dashboard.models import JobListing, Company


def test_insert_job_then_job_exists(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )

    assert job_exists(conn, job.job_url) is False
    inserted = insert_job(conn, job)
    assert inserted is True
    assert job_exists(conn, job.job_url) is True


def test_insert_job_is_idempotent_on_job_url(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )
    insert_job(conn, job)
    second_insert = insert_job(conn, job)

    assert second_insert is False
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert count == 1


def test_upsert_company_inserts_then_updates_without_clobbering_contact(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_company(conn, Company(name="Acme", funding_amount="$1M"))
    conn.execute(
        "UPDATE companies SET contact_email = ? WHERE name = ?",
        ("ceo@acme.com", "Acme"),
    )
    conn.commit()

    upsert_company(conn, Company(name="Acme", funding_amount="$2M"))

    row = conn.execute(
        "SELECT funding_amount, contact_email FROM companies WHERE name = ?",
        ("Acme",),
    ).fetchone()
    assert row[0] == "$2M"
    assert row[1] == "ceo@acme.com"
    count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.db'`

- [ ] **Step 3: Implement `db.py`**

```python
# src/job_dashboard/db.py
import sqlite3
from datetime import datetime, timezone

from job_dashboard.models import Company, JobListing

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT NOT NULL,
    job_url TEXT NOT NULL UNIQUE,
    job_type TEXT,
    is_remote INTEGER,
    salary_text TEXT,
    posted_date TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    funding_amount TEXT,
    funding_round TEXT,
    sector TEXT,
    hq TEXT,
    founders TEXT,
    source TEXT,
    contact_email TEXT,
    contact_source TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""


def init_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def job_exists(conn, job_url):
    row = conn.execute("SELECT 1 FROM jobs WHERE job_url = ?", (job_url,)).fetchone()
    return row is not None


def insert_job(conn, job: JobListing):
    if job_exists(conn, job.job_url):
        return False
    conn.execute(
        """INSERT INTO jobs
           (source, external_id, title, company, location, description,
            job_url, job_type, is_remote, salary_text, posted_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job.source, job.external_id, job.title, job.company, job.location,
            job.description, job.job_url, job.job_type,
            int(job.is_remote) if job.is_remote is not None else None,
            job.salary_text, job.posted_date,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return True


def upsert_company(conn, company: Company):
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM companies WHERE name = ?", (company.name,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE companies SET funding_amount = ?, funding_round = ?,
               sector = ?, hq = ?, founders = ?, last_seen_at = ?
               WHERE name = ?""",
            (company.funding_amount, company.funding_round, company.sector,
             company.hq, company.founders, now, company.name),
        )
    else:
        conn.execute(
            """INSERT INTO companies
               (name, funding_amount, funding_round, sector, hq, founders,
                source, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company.name, company.funding_amount, company.funding_round,
             company.sector, company.hq, company.founders, company.source,
             now, now),
        )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/db.py tests/test_db.py
git commit -m "feat: add SQLite schema with job dedup and company upsert"
```

---

### Task 3: JobSpy source

**Files:**
- Create: `src/job_dashboard/sources/jobspy_source.py`
- Create: `tests/test_jobspy_source.py`

**Interfaces:**
- Produces: `fetch_jobspy_jobs(search_term, location, site_names, results_wanted=20) -> list[JobListing]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobspy_source.py
import pandas as pd

from job_dashboard.sources import jobspy_source


def test_fetch_jobspy_jobs_maps_dataframe_rows_to_joblistings(monkeypatch):
    fake_df = pd.DataFrame([
        {
            "id": "in-123", "site": "indeed", "title": "Machine Learning Engineer",
            "company": "Acme AI", "location": "Remote",
            "description": "Full JD text here", "job_url": "https://indeed.com/job/123",
            "job_type": "fulltime", "is_remote": True,
            "min_amount": 120000, "max_amount": 160000, "currency": "USD",
            "date_posted": "2026-07-01",
        }
    ])
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("machine learning engineer", "Remote", ["indeed"])

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jobspy:indeed"
    assert job.title == "Machine Learning Engineer"
    assert job.company == "Acme AI"
    assert job.job_url == "https://indeed.com/job/123"
    assert job.is_remote is True
    assert job.salary_text == "120000-160000 USD"


def test_fetch_jobspy_jobs_handles_missing_salary(monkeypatch):
    fake_df = pd.DataFrame([
        {
            "id": "li-1", "site": "linkedin", "title": "AI Engineer", "company": "Beta",
            "location": "Bangalore", "description": "JD text",
            "job_url": "https://linkedin.com/job/1", "job_type": "fulltime",
            "is_remote": False, "min_amount": None, "max_amount": None,
            "currency": None, "date_posted": "2026-07-02",
        }
    ])
    monkeypatch.setattr(jobspy_source, "scrape_jobs", lambda **kwargs: fake_df)

    jobs = jobspy_source.fetch_jobspy_jobs("ai engineer", "Bangalore", ["linkedin"])

    assert jobs[0].salary_text is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jobspy_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.sources.jobspy_source'`

- [ ] **Step 3: Implement `jobspy_source.py`**

```python
# src/job_dashboard/sources/jobspy_source.py
from jobspy import scrape_jobs

from job_dashboard.models import JobListing


def fetch_jobspy_jobs(search_term, location, site_names, results_wanted=20):
    df = scrape_jobs(
        site_name=site_names,
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        description_format="markdown",
    )
    jobs = []
    for _, row in df.iterrows():
        jobs.append(
            JobListing(
                source=f"jobspy:{row.get('site')}",
                external_id=str(row.get("id")) if row.get("id") is not None else None,
                title=row.get("title"),
                company=row.get("company"),
                location=row.get("location"),
                description=row.get("description") or "",
                job_url=row.get("job_url"),
                job_type=row.get("job_type"),
                is_remote=bool(row.get("is_remote")) if row.get("is_remote") is not None else None,
                salary_text=_format_salary(row),
                posted_date=str(row.get("date_posted")) if row.get("date_posted") is not None else None,
            )
        )
    return jobs


def _format_salary(row):
    lo, hi, cur = row.get("min_amount"), row.get("max_amount"), row.get("currency")
    if not lo and not hi:
        return None
    return f"{lo or ''}-{hi or ''} {cur or ''}".strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jobspy_source.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/sources/jobspy_source.py tests/test_jobspy_source.py
git commit -m "feat: add JobSpy source (Indeed/LinkedIn/Naukri/Glassdoor/etc)"
```

---

### Task 4: Shared test fixture (`FakeResponse`)

**Files:**
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `FakeResponse(json_data=None, text="", status_code=200)` — pytest fixture-free helper class imported directly by the remaining source tests (Tasks 5–8).

- [ ] **Step 1: Write `conftest.py`**

```python
# tests/conftest.py
class FakeResponse:
    def __init__(self, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data
```

- [ ] **Step 2: Verify it's picked up by pytest (no test yet, so just check for import errors)**

Run: `pytest --collect-only -q`
Expected: collection succeeds with no errors (existing tests from Tasks 1–3 still listed)

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared FakeResponse helper for HTTP-mocked source tests"
```

---

### Task 5: Remotive + RemoteOK sources

**Files:**
- Create: `src/job_dashboard/sources/remotive_source.py`
- Create: `src/job_dashboard/sources/remoteok_source.py`
- Create: `tests/test_remotive_source.py`
- Create: `tests/test_remoteok_source.py`

**Interfaces:**
- Produces: `fetch_remotive_jobs(search_term, limit=50) -> list[JobListing]`
- Produces: `fetch_remoteok_jobs() -> list[JobListing]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_remotive_source.py
from job_dashboard.sources import remotive_source
from tests.conftest import FakeResponse


def test_fetch_remotive_jobs_maps_response(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 987, "title": "AI Engineer", "company_name": "Remote Co",
                "candidate_required_location": "Worldwide",
                "description": "<p>Build AI systems</p>",
                "url": "https://remotive.com/job/987",
                "job_type": "full_time", "salary": "$120,000 - $150,000",
                "publication_date": "2026-07-05T00:00:00",
            }
        ]
    }
    monkeypatch.setattr(
        remotive_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remotive_source.fetch_remotive_jobs("AI engineer")

    assert len(jobs) == 1
    assert jobs[0].source == "remotive"
    assert jobs[0].title == "AI Engineer"
    assert jobs[0].job_url == "https://remotive.com/job/987"
    assert jobs[0].is_remote is True
```

```python
# tests/test_remoteok_source.py
from job_dashboard.sources import remoteok_source
from tests.conftest import FakeResponse


def test_fetch_remoteok_jobs_skips_legal_notice_and_maps_jobs(monkeypatch):
    payload = [
        {"legal": "API Terms of Service..."},
        {
            "id": "555", "position": "Senior Data Scientist", "company": "DataCo",
            "location": "", "description": "Analyze data at scale",
            "apply_url": "https://remoteok.com/remote-jobs/555",
            "tags": ["python", "contract"],
            "salary_min": 100000, "salary_max": 140000,
            "date": "2026-07-08T00:00:00",
        },
    ]
    monkeypatch.setattr(
        remoteok_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = remoteok_source.fetch_remoteok_jobs()

    assert len(jobs) == 1
    assert jobs[0].title == "Senior Data Scientist"
    assert jobs[0].job_type == "contract"
    assert jobs[0].salary_text == "$100000-$140000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_remotive_source.py tests/test_remoteok_source.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `remotive_source.py`**

```python
# src/job_dashboard/sources/remotive_source.py
import requests

from job_dashboard.models import JobListing

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"


def fetch_remotive_jobs(search_term, limit=50):
    response = requests.get(
        REMOTIVE_API_URL, params={"search": search_term, "limit": limit}, timeout=15
    )
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(
            JobListing(
                source="remotive",
                external_id=str(item.get("id")),
                title=item.get("title"),
                company=item.get("company_name"),
                location=item.get("candidate_required_location"),
                description=item.get("description") or "",
                job_url=item.get("url"),
                job_type=item.get("job_type"),
                is_remote=True,
                salary_text=item.get("salary") or None,
                posted_date=item.get("publication_date"),
            )
        )
    return jobs
```

- [ ] **Step 4: Implement `remoteok_source.py`**

```python
# src/job_dashboard/sources/remoteok_source.py
import requests

from job_dashboard.models import JobListing

REMOTEOK_API_URL = "https://remoteok.com/api"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobDashboardBot/1.0)"}


def fetch_remoteok_jobs():
    response = requests.get(REMOTEOK_API_URL, headers=_HEADERS, timeout=15)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data:
        if "position" not in item:
            continue  # first element is the API's legal notice, not a job
        jobs.append(
            JobListing(
                source="remoteok",
                external_id=str(item.get("id")),
                title=item.get("position"),
                company=item.get("company"),
                location=item.get("location") or "Remote",
                description=item.get("description") or "",
                job_url=item.get("apply_url") or item.get("url"),
                job_type="contract" if "contract" in (item.get("tags") or []) else None,
                is_remote=True,
                salary_text=_format_salary(item),
                posted_date=item.get("date"),
            )
        )
    return jobs


def _format_salary(item):
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if not lo and not hi:
        return None
    return f"${lo or ''}-${hi or ''}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_remotive_source.py tests/test_remoteok_source.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/sources/remotive_source.py src/job_dashboard/sources/remoteok_source.py tests/test_remotive_source.py tests/test_remoteok_source.py
git commit -m "feat: add Remotive and RemoteOK free-API sources"
```

---

### Task 6: We Work Remotely (RSS) + Himalayas sources

**Files:**
- Create: `src/job_dashboard/sources/wwr_source.py`
- Create: `src/job_dashboard/sources/himalayas_source.py`
- Create: `tests/test_wwr_source.py`
- Create: `tests/test_himalayas_source.py`

**Interfaces:**
- Produces: `fetch_wwr_jobs(feed_url="https://weworkremotely.com/categories/remote-programming-jobs.rss") -> list[JobListing]`
- Produces: `fetch_himalayas_jobs(query, employment_type=None) -> list[JobListing]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wwr_source.py
import feedparser

from job_dashboard.sources import wwr_source

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>We Work Remotely</title>
<item>
<title>Acme Corp: Senior Machine Learning Engineer</title>
<link>https://weworkremotely.com/remote-jobs/acme-corp-senior-machine-learning-engineer</link>
<description>&lt;p&gt;Full job description text&lt;/p&gt;</description>
<pubDate>Sat, 05 Jul 2026 00:00:00 +0000</pubDate>
</item>
</channel>
</rss>"""


def test_fetch_wwr_jobs_splits_company_from_title(monkeypatch):
    monkeypatch.setattr(
        wwr_source.feedparser, "parse", lambda url: feedparser.parse(SAMPLE_RSS)
    )

    jobs = wwr_source.fetch_wwr_jobs()

    assert len(jobs) == 1
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].title == "Senior Machine Learning Engineer"
    assert jobs[0].job_url.startswith("https://weworkremotely.com")
    assert jobs[0].is_remote is True
```

```python
# tests/test_himalayas_source.py
from job_dashboard.sources import himalayas_source
from tests.conftest import FakeResponse


def test_fetch_himalayas_jobs_maps_response(monkeypatch):
    payload = {
        "jobs": [
            {
                "guid": "abc-123", "title": "Senior ML Engineer",
                "companyName": "Himalayas Co", "employmentType": "Full Time",
                "locationRestrictions": ["United States", "India"],
                "description": "<p>Own the ML platform</p>",
                "applicationLink": "https://himalayas.app/jobs/abc-123",
                "minSalary": 130000, "maxSalary": 170000, "currency": "USD",
                "pubDate": "2026-07-06T00:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(
        himalayas_source.requests, "get", lambda *a, **k: FakeResponse(json_data=payload)
    )

    jobs = himalayas_source.fetch_himalayas_jobs("machine learning")

    assert len(jobs) == 1
    assert jobs[0].title == "Senior ML Engineer"
    assert jobs[0].location == "United States, India"
    assert jobs[0].salary_text == "130000-170000 USD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wwr_source.py tests/test_himalayas_source.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `wwr_source.py`**

```python
# src/job_dashboard/sources/wwr_source.py
import feedparser

from job_dashboard.models import JobListing


def fetch_wwr_jobs(feed_url="https://weworkremotely.com/categories/remote-programming-jobs.rss"):
    parsed = feedparser.parse(feed_url)
    jobs = []
    for entry in parsed.entries:
        raw_title = entry.get("title", "")
        jobs.append(
            JobListing(
                source="weworkremotely",
                title=_job_title(raw_title),
                company=_company(raw_title),
                location="Remote",
                description=entry.get("summary", ""),
                job_url=entry.get("link"),
                job_type=None,
                is_remote=True,
                posted_date=entry.get("published"),
            )
        )
    return jobs


def _job_title(raw_title):
    # WWR titles are formatted "Company: Job Title"
    return raw_title.split(":", 1)[1].strip() if ":" in raw_title else raw_title


def _company(raw_title):
    return raw_title.split(":", 1)[0].strip() if ":" in raw_title else "Unknown"
```

- [ ] **Step 4: Implement `himalayas_source.py`**

```python
# src/job_dashboard/sources/himalayas_source.py
import requests

from job_dashboard.models import JobListing

HIMALAYAS_SEARCH_URL = "https://himalayas.app/jobs/api/search"


def fetch_himalayas_jobs(query, employment_type=None):
    params = {"q": query}
    if employment_type:
        params["employment_type"] = employment_type
    response = requests.get(HIMALAYAS_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(
            JobListing(
                source="himalayas",
                external_id=item.get("guid"),
                title=item.get("title"),
                company=item.get("companyName"),
                location=", ".join(item.get("locationRestrictions") or []) or "Worldwide",
                description=item.get("description") or "",
                job_url=item.get("applicationLink"),
                job_type=item.get("employmentType"),
                is_remote=True,
                salary_text=_format_salary(item),
                posted_date=item.get("pubDate"),
            )
        )
    return jobs


def _format_salary(item):
    lo, hi, cur = item.get("minSalary"), item.get("maxSalary"), item.get("currency")
    if lo is None and hi is None:
        return None
    return f"{lo or ''}-{hi or ''} {cur or ''}".strip()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_wwr_source.py tests/test_himalayas_source.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/sources/wwr_source.py src/job_dashboard/sources/himalayas_source.py tests/test_wwr_source.py tests/test_himalayas_source.py
git commit -m "feat: add We Work Remotely (RSS) and Himalayas sources"
```

---

### Task 7: Startup funding sheet source

**Files:**
- Create: `src/job_dashboard/sources/startup_sheet.py`
- Create: `tests/test_startup_sheet.py`

**Interfaces:**
- Produces: `fetch_funded_startups(sheet_id="19zHtZ1F8-PD8THr8AJ7iN-cyES-5UHWGua_oPERnDvQ") -> list[Company]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_startup_sheet.py
from job_dashboard.sources import startup_sheet
from tests.conftest import FakeResponse

SAMPLE_CSV = (
    '"Company","Money Raised","Round","Month (2026)","Sector","HQ","Founders"\n'
    '"Anthropic","$50B","Series H","May","AI","San Francisco, CA","Dario Amodei"\n'
    '"","","","","","",""\n'
)


def test_fetch_funded_startups_parses_csv_and_skips_blank_rows(monkeypatch):
    monkeypatch.setattr(
        startup_sheet.requests, "get", lambda *a, **k: FakeResponse(text=SAMPLE_CSV)
    )

    companies = startup_sheet.fetch_funded_startups()

    assert len(companies) == 1
    assert companies[0].name == "Anthropic"
    assert companies[0].funding_amount == "$50B"
    assert companies[0].sector == "AI"
    assert companies[0].source == "startup_sheet"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_startup_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `startup_sheet.py`**

```python
# src/job_dashboard/sources/startup_sheet.py
import csv
import io

import requests

from job_dashboard.models import Company

SHEET_CSV_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"


def fetch_funded_startups(sheet_id="19zHtZ1F8-PD8THr8AJ7iN-cyES-5UHWGua_oPERnDvQ"):
    url = SHEET_CSV_URL_TEMPLATE.format(sheet_id=sheet_id)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    companies = []
    for row in reader:
        name = (row.get("Company") or "").strip()
        if not name:
            continue
        companies.append(
            Company(
                name=name,
                funding_amount=row.get("Money Raised"),
                funding_round=row.get("Round"),
                sector=row.get("Sector"),
                hq=row.get("HQ"),
                founders=row.get("Founders"),
                source="startup_sheet",
            )
        )
    return companies
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_startup_sheet.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/job_dashboard/sources/startup_sheet.py tests/test_startup_sheet.py
git commit -m "feat: add recently-funded-startups sheet source"
```

---

### Task 8: `ingest.py` orchestration

**Files:**
- Create: `src/job_dashboard/ingest.py`
- Create: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `init_db`, `insert_job`, `upsert_company` from `job_dashboard.db`
- Produces: `run_ingest(conn, job_sources, company_sources) -> dict` with keys `new_jobs`, `companies_seen`. `job_sources`/`company_sources` are lists of no-arg callables returning `list[JobListing]`/`list[Company]` — every source function from Tasks 3, 5, 6, 7 fits this signature already.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest.py
from job_dashboard import ingest
from job_dashboard.db import init_db
from job_dashboard.models import Company, JobListing


def test_run_ingest_dedupes_jobs_and_upserts_companies(tmp_path):
    conn = init_db(tmp_path / "test.db")
    job = JobListing(
        source="test", title="ML Engineer", company="Acme",
        job_url="https://example.com/1", description="desc",
    )
    company = Company(name="Acme", funding_amount="$1M")

    result = ingest.run_ingest(
        conn,
        job_sources=[lambda: [job], lambda: [job]],  # duplicate source on purpose
        company_sources=[lambda: [company]],
    )

    assert result == {"new_jobs": 1, "companies_seen": 1}
    row_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert row_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_dashboard.ingest'`

- [ ] **Step 3: Implement `ingest.py`**

```python
# src/job_dashboard/ingest.py
from job_dashboard.db import insert_job, upsert_company


def run_ingest(conn, job_sources, company_sources):
    """job_sources/company_sources: lists of no-arg callables returning
    list[JobListing] / list[Company] respectively."""
    new_jobs = 0
    for fetch in job_sources:
        for job in fetch():
            if insert_job(conn, job):
                new_jobs += 1

    companies_seen = 0
    for fetch in company_sources:
        for company in fetch():
            upsert_company(conn, company)
            companies_seen += 1

    return {"new_jobs": new_jobs, "companies_seen": companies_seen}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: all tests across Tasks 1–8 pass (13 passed)

- [ ] **Step 6: Commit**

```bash
git add src/job_dashboard/ingest.py tests/test_ingest.py
git commit -m "feat: add ingest orchestration tying all sources into the DB"
```

---

## What this plan does not cover (by design — see Global Constraints)

- Scrapling-based sources (Wellfound, jobs24x, unlistedjobs, remotejobs.io) — follow-up plan
- agent-reach 24h social-signal monitoring — follow-up plan
- Research fellowship/residency curated list (Anthropic Fellows Program, etc.) — not yet designed which specific programs/URLs to track; small enough to add as a short follow-up task once the list is chosen
- Semantic matching/ranking against the Profile — separate plan, needs both this plan and the Profile plan done first
- Scheduling/cron for periodic re-ingestion — implementation detail to decide once this runs manually end-to-end
