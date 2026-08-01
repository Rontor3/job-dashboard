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
    # Registers NaukriLoginClient.restore_session (NopeRi has no built-in
    # equivalent) — must be imported before it's called below.
    from job_dashboard.sources import naukri_session_shim  # noqa: F401
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
        logger.warning("Naukri fetch failed (%s): %s", search_term, type(exc).__name__)
        return []

    jobs = []
    for r in raw_jobs or []:
        description = getattr(r, "description", "") or ""
        if not str(description).strip():
            continue
        title = _text(getattr(r, "title", None))
        company = _text(getattr(r, "company", None))
        job_url = getattr(r, "apply_link", None)
        # Skip rows missing required non-null fields
        if not title or not company or not job_url:
            continue
        jobs.append(
            JobListing(
                source="naukri",
                external_id=str(getattr(r, "job_id", "") or "") or None,
                title=title,
                company=company,
                # Naukri's API returns some fields (salary, location) as nested
                # dicts/lists; coerce to plain text so the DB bind never sees a dict.
                location=_text(getattr(r, "location", None)),
                description=description,
                job_url=job_url,
                job_type=None,
                is_remote=False,
                salary_text=_text(getattr(r, "salary", None)),
                posted_date=_text(getattr(r, "posted_date", None)),
            )
        )
    return jobs


def _text(v):
    """Coerce a Naukri field to plain text (or None). Handles the nested
    dict/list shapes their API returns for salary, location, etc."""
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        for k in ("label", "text", "display", "value", "name"):
            if v.get(k):
                return str(v[k]).strip() or None
        return None
    if isinstance(v, (list, tuple)):
        parts = [_text(x) for x in v]
        return ", ".join(p for p in parts if p) or None
    return str(v).strip() or None


def _accepts_kw(client):
    # NopeRi's search_jobs signature is (keyword, ...); the fake in tests also
    # takes keyword. Kept tolerant so a positional-only fake still works.
    import inspect
    try:
        return "keyword" in inspect.signature(client.search_jobs).parameters
    except (TypeError, ValueError):
        return False
