"""Headless résumé push for the Naukri hybrid apply.

The ONLY module that imports NopeRi write code (update_resume). NopeRi's
apply / questionnaire / auto-apply-agent modules are never imported here.
Pushes the tailored résumé to the Naukri profile, then read-back-verifies it is
live before the browser step is allowed to apply (Naukri processes uploads
asynchronously — applying too early sends the old file). Never raises.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SESSION_PATH = Path("data/naukri_session.json")


@dataclass
class PushResult:
    ok: bool
    live_resume_name: str | None = None
    error: str | None = None


def _default_client_factory(session):
    """Build NopeRi's login client (which owns update_resume) from a cached
    session. Imported lazily so curl_cffi / NopeRi stay off everyone else's
    import path. Résumé-write surface only — never apply code."""
    import sys
    vendor = Path(__file__).resolve().parents[3] / "vendor" / "NopeRi"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from job_dashboard.sources import naukri_session_shim  # noqa: F401 (registers restore_session)
    from src.client.naukri_client import NaukriLoginClient  # type: ignore
    login = NaukriLoginClient.__new__(NaukriLoginClient)
    login.restore_session(session)
    return login


def _status_ok(status):
    try:
        return 200 <= int(status) < 300
    except (TypeError, ValueError):
        return False


def _live_name(client):
    """Best-effort read of the résumé name Naukri currently reports live."""
    for attr in ("current_resume_name", "fetch_resume_name"):
        fn = getattr(client, attr, None)
        if callable(fn):
            return fn()
    return None


def push_resume(pdf_path, session_path=DEFAULT_SESSION_PATH, verify=True,
                client_factory=None, poll=(5, 2)):
    session_path = Path(session_path)
    if not session_path.exists():
        return PushResult(False, error="no_session")
    try:
        session = json.loads(session_path.read_text())
    except (OSError, ValueError):
        return PushResult(False, error="no_session")

    factory = client_factory or _default_client_factory
    try:
        client = factory(session)
        result = client.update_resume(pdf_path)
        if not _status_ok(getattr(result, "status_code", None)):
            return PushResult(False, error="upload_rejected")
        if not verify:
            return PushResult(True)

        want = os.path.basename(str(pdf_path)).lower()
        attempts, delay = poll
        for _ in range(max(1, int(attempts))):
            live = _live_name(client)
            if live and os.path.basename(str(live)).lower() == want:
                return PushResult(True, live_resume_name=live)
            if delay:
                time.sleep(delay)
        return PushResult(False, error="verify_timeout")
    except Exception as exc:  # blocked, token expired, API shape change, etc.
        logger.warning("Naukri résumé push failed: %s", type(exc).__name__)
        return PushResult(False, error=type(exc).__name__)
