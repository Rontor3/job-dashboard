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

# Load .env BEFORE importing the app so the key is in os.environ for every
# request handler (company_research reads it lazily at call time).
load_env_file()


from job_dashboard.api.app import create_app  # noqa: E402
from job_dashboard.linkedin.cdp_fetch import CdpHiringFetcher  # noqa: E402
from job_dashboard.match.embedder import load_default_model  # noqa: E402

# Hiring posts come through the user's own logged-in Chrome over CDP (port 9222).
# The cookie-based LinkedInBrowserFetcher (li_at/JSESSIONID in .env) is
# superseded; kept in linkedin/browser_fetch.py for reference only.
_fetcher = CdpHiringFetcher()
try:
    _model = load_default_model()
except Exception:
    _model = None

app = create_app(hiring_fetcher=_fetcher, embed_model=_model)

__all__ = ["app"]
