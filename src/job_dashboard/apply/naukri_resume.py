"""Headless résumé push for the Naukri hybrid apply.

The ONLY module that imports NopeRi write code (update_resume). NopeRi's
apply / questionnaire / auto-apply-agent modules are never imported here.
Pushes the tailored résumé to the Naukri profile before the browser step
applies (Naukri processes uploads asynchronously, so we pause briefly to let it
settle). NopeRi exposes no live-résumé read-back, so "verify" means: a 2xx from
update_resume is the accept signal, and the response body is scanned best-effort
for the pushed filename — a match confirms it, a miss still returns ok (accepted,
name unconfirmable). Never hard-fails on an unconfirmable name. Never raises.
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


def _body_mentions(body, needle):
    """Best-effort: does the update response echo the pushed filename?"""
    if not needle:
        return False
    try:
        return needle in json.dumps(body, default=str).lower()
    except Exception:
        return False


def push_resume(pdf_path, session_path=DEFAULT_SESSION_PATH, verify=True,
                client_factory=None, settle_seconds=2.0):
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

        # Let Naukri process the async upload, then best-effort confirm the
        # filename from the update response body. No live read-back exists.
        if settle_seconds:
            time.sleep(settle_seconds)
        basename = os.path.basename(str(pdf_path))
        body = getattr(result, "raw_response", None)
        live = basename if _body_mentions(body, basename.lower()) else None
        return PushResult(True, live_resume_name=live)
    except Exception as exc:  # blocked, token expired, API shape change, etc.
        logger.warning("Naukri résumé push failed: %s", type(exc).__name__)
        return PushResult(False, error=type(exc).__name__)
