# Naukri Source (via NopeRi) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox steps.

**Goal:** Read-only Naukri job source using the vendored NopeRi client — a one-time/occasional interactive login script that caches a session, and an unattended pipeline source that reads that cached session to search + map jobs. Apply code never imported.

**Architecture:** NopeRi vendored under `vendor/NopeRi/` (gitignored). `scripts/naukri_login.py` handles interactive login + OTP and writes `data/naukri_session.json`. `sources/naukri_source.py` loads that session and calls NopeRi's search, mapping `Job → JobListing`; returns `[]` when no session / on any error (per-source isolation). Registry swaps the dead `jobspy:naukri` fetcher for this.

**Tech Stack:** Python 3.11+, vendored NopeRi (curl_cffi/pycryptodome), pytest (all NopeRi calls mocked).

## Global Constraints

- **Read-only.** Never import or call NopeRi's `apply_job`, `apply_agent`, resume-upload, or profile-update code. Only login (in the script) + search (in the source).
- **Credentials never touched by code beyond os.getenv.** `NAUKRI_USERNAME`/`NAUKRI_PASSWORD` read from env only; never logged, never written to any file, never committed. The password is the user's to set in `.env`.
- Every `JobListing` carries full description text; rows lacking one are skipped (existing project rule).
- No test performs a real network call, imports the real NopeRi network stack, or needs credentials — the NopeRi client is injected/mocked.
- `naukri_source.fetch_naukri_jobs` must never raise into the pipeline: missing session, expired token, import error, or NopeRi exception all resolve to `[]` (run_ingest already isolates per source, but this source degrades quietly on the common no-session case).
- Session cache `data/naukri_session.json` is gitignored (data/ already is via data/*.db — add explicit line).

---

### Task 1: `naukri_source.py` — session-backed search → JobListing (mocked)

**Files:** Create `src/job_dashboard/sources/naukri_source.py`, `tests/test_naukri_source.py`

**Interfaces:**
- `fetch_naukri_jobs(search_term, session_path=DEFAULT_SESSION_PATH, client_factory=None) -> list[JobListing]`
- `client_factory(session_dict) -> object` returns something exposing `.search_jobs(keyword) -> list[Job-like]` where each Job-like has attributes `job_id, title, company, location, experience, salary, posted_date, apply_link, description, tags`. Default factory builds the real NopeRi client (import-guarded). Tests inject a fake.
- Session file shape: `{"token": "...", "cookies": {...}, "saved_at": "iso"}`. Missing file → `[]`.

- [ ] Step 1 — failing tests:

```python
# tests/test_naukri_source.py
import json
from dataclasses import dataclass

from job_dashboard.sources import naukri_source
from job_dashboard.models import JobListing


@dataclass
class FakeJob:
    job_id: str = "j1"
    title: str = "ML Engineer"
    company: str = "Acme"
    location: str = "Bengaluru"
    experience: str = "2-5 Yrs"
    salary: str = ""
    posted_date: str = "3 Days Ago"
    apply_link: str = "https://www.naukri.com/job-listings-ml-1"
    description: str = "Build ML pipelines in production."
    tags: tuple = ("python", "ml")


class FakeClient:
    def __init__(self, jobs):
        self._jobs = jobs
    def search_jobs(self, keyword):
        return self._jobs


def _write_session(tmp_path):
    p = tmp_path / "naukri_session.json"
    p.write_text(json.dumps({"token": "t", "cookies": {}, "saved_at": "2026-07-17"}))
    return p


def test_maps_naukri_jobs_to_joblistings(tmp_path):
    sp = _write_session(tmp_path)
    jobs = naukri_source.fetch_naukri_jobs(
        "machine learning engineer", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob()]),
    )
    assert len(jobs) == 1
    j = jobs[0]
    assert isinstance(j, JobListing)
    assert j.source == "naukri"
    assert j.title == "ML Engineer"
    assert j.company == "Acme"
    assert j.job_url == "https://www.naukri.com/job-listings-ml-1"
    assert j.description == "Build ML pipelines in production."
    assert j.location == "Bengaluru"
    assert j.is_remote is False


def test_skips_jobs_without_description(tmp_path):
    sp = _write_session(tmp_path)
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=sp,
        client_factory=lambda sess: FakeClient([FakeJob(description="")]),
    )
    assert jobs == []


def test_returns_empty_when_no_session_file(tmp_path):
    jobs = naukri_source.fetch_naukri_jobs(
        "ml", session_path=tmp_path / "missing.json",
        client_factory=lambda sess: FakeClient([FakeJob()]),
    )
    assert jobs == []


def test_returns_empty_when_client_raises(tmp_path):
    sp = _write_session(tmp_path)
    def boom(_sess):
        raise RuntimeError("naukri blocked / token expired")
    jobs = naukri_source.fetch_naukri_jobs("ml", session_path=sp, client_factory=boom)
    assert jobs == []


def test_returns_empty_when_search_raises(tmp_path):
    sp = _write_session(tmp_path)
    class Angry:
        def search_jobs(self, keyword):
            raise RuntimeError("403")
    jobs = naukri_source.fetch_naukri_jobs("ml", session_path=sp,
                                           client_factory=lambda s: Angry())
    assert jobs == []
```

- [ ] Step 2 — run `python3 -m pytest tests/test_naukri_source.py -v` → FAIL (module missing).
- [ ] Step 3 — implement:

```python
# src/job_dashboard/sources/naukri_source.py
"""Read-only Naukri source backed by the vendored NopeRi search client.

Only login (via scripts/naukri_login.py) and search are used — NopeRi's
apply / resume-upload / profile code is never imported here. The pipeline
reads a cached session written by that script; with no session or on any
error this returns [] so a blocked/expired Naukri never breaks a refresh.
"""
import json
import logging
from pathlib import Path

from job_dashboard.models import JobListing

logger = logging.getLogger(__name__)

DEFAULT_SESSION_PATH = Path("data/naukri_session.json")


def _default_client_factory(session):
    """Build the real NopeRi search client from a cached session dict.

    Imported lazily and behind the caller — keeps curl_cffi/pycryptodome and
    the NopeRi package off the import path for everyone who isn't running a
    live Naukri fetch (tests, other sources, the API)."""
    import sys
    vendor = Path(__file__).resolve().parents[3] / "vendor" / "NopeRi"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from src.client.naukri_client import NaukriLoginClient  # type: ignore
    from src.client.job_client import NaukriJobClient  # type: ignore

    login = NaukriLoginClient.__new__(NaukriLoginClient)
    login.restore_session(session)  # token + cookies, no network
    return NaukriJobClient(login)


def fetch_naukri_jobs(search_term, session_path=DEFAULT_SESSION_PATH, client_factory=None):
    session_path = Path(session_path)
    if not session_path.exists():
        logger.info("No Naukri session at %s — run scripts/naukri_login.py", session_path)
        return []
    try:
        session = json.loads(session_path.read_text())
    except (OSError, ValueError):
        logger.warning("Unreadable Naukri session file %s", session_path)
        return []

    factory = client_factory or _default_client_factory
    try:
        client = factory(session)
        raw_jobs = client.search_jobs(keyword=search_term) if _accepts_kw(client) else client.search_jobs(search_term)
    except Exception as exc:  # blocked, token expired, import failure, etc.
        logger.warning("Naukri fetch failed (%s): %s", search_term, exc)
        return []

    jobs = []
    for r in raw_jobs or []:
        description = getattr(r, "description", "") or ""
        if not str(description).strip():
            continue
        jobs.append(
            JobListing(
                source="naukri",
                external_id=str(getattr(r, "job_id", "") or "") or None,
                title=getattr(r, "title", None),
                company=getattr(r, "company", None),
                location=getattr(r, "location", None),
                description=description,
                job_url=getattr(r, "apply_link", None),
                job_type=None,
                is_remote=False,
                salary_text=(getattr(r, "salary", "") or None),
                posted_date=(getattr(r, "posted_date", "") or None),
            )
        )
    return jobs


def _accepts_kw(client):
    # NopeRi's search_jobs signature is (keyword, ...); the fake in tests also
    # takes keyword. Kept tolerant so a positional-only fake still works.
    import inspect
    try:
        return "keyword" in inspect.signature(client.search_jobs).parameters
    except (TypeError, ValueError):
        return False
```

- [ ] Step 4 — `python3 -m pytest tests/test_naukri_source.py -v` → PASS (5).
- [ ] Step 5 — `python3 -m pytest` → full suite green.
- [ ] Step 6 — commit `feat: read-only Naukri source via vendored NopeRi (session-backed, mocked tests)`.

---

### Task 2: interactive login script + vendor + registry wiring + gitignore

**Files:** Create `scripts/naukri_login.py`; vendor `vendor/NopeRi/` (gitignored); Modify `src/job_dashboard/source_registry.py`, `.gitignore`, `requirements.txt`.

**Interfaces:** `scripts/naukri_login.py` run as `python3 scripts/naukri_login.py` — reads env creds, logs in (handles OTP prompt), writes `data/naukri_session.json`. Registry adds `fetch_naukri_jobs` for the search terms (replacing the dead jobspy:naukri entry). NopeRi must expose `restore_session(dict)` + a way to serialize the session — add a thin shim if upstream lacks it.

- [ ] Step 1 — vendor the repo (gitignored, not committed):

```bash
git clone --depth 1 https://github.com/Traverser25/NopeRi.git vendor/NopeRi
rm -rf vendor/NopeRi/.git
```

- [ ] Step 2 — add to `.gitignore`:

```
vendor/NopeRi/
data/naukri_session.json
```

- [ ] Step 3 — add optional deps to `requirements.txt` (commented as Naukri-only, import-guarded):

```
# Naukri source (optional — only needed for the vendored NopeRi Naukri fetcher)
curl_cffi>=0.7
pycryptodome>=3.20
```

- [ ] Step 4 — inspect NopeRi's `NaukriLoginClient` for existing token/cookie accessors. If it lacks `restore_session`/serialization, add a minimal shim module `vendor/NopeRi/session_shim.py` (or patch naukri_client) exposing:
  - `serialize_session(login_client) -> dict` (token + cookies)
  - `restore_session(login_client, dict)` (set token + cookies, no network)
  Reference the real attribute names found in `src/client/naukri_client.py` (e.g. `self.token`, `self.session.cookies`). Do NOT touch apply code.

- [ ] Step 5 — write `scripts/naukri_login.py`:

```python
"""Interactive Naukri login → caches a session for the unattended source.

Run occasionally (session is IP-bound and can expire). Reads credentials
from the environment / .env; NEVER prints or stores the password. If Naukri
issues an OTP challenge, prompts for the 6-digit code.

    python3 scripts/naukri_login.py
"""
import json
import os
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "NopeRi"
sys.path.insert(0, str(VENDOR))
SESSION_PATH = Path(__file__).resolve().parents[1] / "data" / "naukri_session.json"


def main():
    user = os.getenv("NAUKRI_USERNAME")
    pw = os.getenv("NAUKRI_PASSWORD")
    if not user or not pw:
        print("Set NAUKRI_USERNAME and NAUKRI_PASSWORD in .env first.")
        return 1

    from src.client.naukri_client import NaukriLoginClient  # type: ignore
    from session_shim import serialize_session  # type: ignore

    client = NaukriLoginClient(user, pw)
    try:
        client.login()
    except Exception as exc:
        # OTP path: NopeRi raises / signals an OTP challenge; prompt for code.
        if "otp" in str(exc).lower():
            code = input("Enter the OTP Naukri sent you: ").strip()
            client.verify_otp(code)
        else:
            print(f"Login failed: {exc}")
            return 1

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(serialize_session(client)))
    print(f"Naukri session cached to {SESSION_PATH}. Refreshes will now include Naukri.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

(Adjust the OTP branch to NopeRi's actual login/OTP control flow found in Step 4 — the login may return a status rather than raise. Keep the password out of all output.)

- [ ] Step 6 — wire the registry: in `source_registry.py`, import `fetch_naukri_jobs`, drop the dead `("India", ["naukri"], None)` jobspy entry, and append `fetchers.append(lambda t=term: fetch_naukri_jobs(t))` inside the per-term loop.

- [ ] Step 7 — `python3 -m pytest tests/test_sources.py -q` → the registry test still passes (it monkeypatches jobspy fetchers; add a monkeypatch for `naukri_source.fetch_naukri_jobs` returning `[]` if the test enumerates all fetchers). Full suite green.

- [ ] Step 8 — commit `feat: interactive naukri_login script + registry wiring (vendored NopeRi, gitignored)`.

---

## Not covered (by design)

- Any apply / resume-upload / profile-update path from NopeRi (read-only source only).
- Live end-to-end test (needs the user's real credentials + a working IP — the user runs `naukri_login.py`, then a normal refresh picks Naukri up).
- OTP automation (OTP is entered by the user in the login script).
- The Application Agent / auto-apply subsystem (separate later sprint, after the Resume Engine).
