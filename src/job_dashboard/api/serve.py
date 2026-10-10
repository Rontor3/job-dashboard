"""Server entry point: load ``.env`` first, THEN build the app.

Run with:  ``python3 -m uvicorn job_dashboard.api.serve:app --port 8000``

This exists so the dashboard process picks up ``TINYFISH_API_KEY`` (and any
other secrets) from the project ``.env`` without every plain
``import job_dashboard.api.app`` doing so -- which would make the
``skipif``-guarded live-smoke tests fire real network calls under pytest.
Tests import ``api.app`` directly and stay key-free; only this module loads
``.env``.
"""

from __future__ import annotations

from job_dashboard.env import load_env_file
from job_dashboard.paths import REPO_ROOT

REPO_ENV = REPO_ROOT / ".env"   # not cwd-relative: the server may start anywhere

# Load .env BEFORE importing the app so the key is in os.environ for every
# request handler (company_research reads it lazily at call time).
load_env_file(REPO_ENV)


from job_dashboard.api.app import create_app  # noqa: E402
from job_dashboard.linkedin.cdp_fetch import CdpHiringFetcher  # noqa: E402
from job_dashboard.linkedin.contacts import judge_post  # noqa: E402
from job_dashboard.match.profile_text import current_resume_text  # noqa: E402
from job_dashboard.db import init_db  # noqa: E402
from job_dashboard.api.app import DEFAULT_DB  # noqa: E402
from job_dashboard.match.embedder import LazyModel  # noqa: E402

# Hiring posts come through the agent's isolated Chrome over CDP (job_dashboard.agent_browser).
# The cookie-based LinkedInBrowserFetcher (li_at/JSESSIONID in .env) is
# superseded; kept in linkedin/browser_fetch.py for reference only.
_fetcher = CdpHiringFetcher()
_model = LazyModel()          # loads in the background; the server answers immediately



def _constraints():
    try:
        conn = init_db(DEFAULT_DB)
        row = conn.execute("SELECT location, work_authorization FROM application_profile").fetchone()
        conn.close()
        return f"Candidate is based in {row[0]}. Work authorization: {row[1]}" if row else ""
    except Exception:  # noqa: BLE001
        return ""


def _judge(post):
    # Re-read each call so replacing data/current_resume.pdf needs no restart.
    return judge_post(post, current_resume_text(), _constraints())


# Hiring posts: Ollama extracts the role title and scores it against the current
# résumé; off-family titles and fits below MIN_FIT are dropped.
app = create_app(hiring_fetcher=_fetcher, embed_model=_model, hiring_role_fn=_judge)

# Daily Gmail scan of the companies we applied to (moves jobs to Interview round /
# Selected / Rejected). Off in tests: they import api.app directly, never serve.
import threading  # noqa: E402

threading.Thread(target=app.state.mail_scanner.loop, name="mail-scan-daily", daemon=True).start()

__all__ = ["app"]
