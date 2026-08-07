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

import os  # noqa: E402  (import after env load, intentional)

from job_dashboard.api.app import create_app  # noqa: E402
from job_dashboard.linkedin.browser_fetch import LinkedInBrowserFetcher  # noqa: E402
from job_dashboard.match.embedder import load_default_model  # noqa: E402

_li, _js = os.getenv("LINKEDIN_LI_AT"), os.getenv("LINKEDIN_JSESSIONID")
# headless=True so Refresh runs behind the scenes — no Chrome window steals
# focus. undetected-chromedriver's stealth still returns real posts headless
# (verified). Set LINKEDIN_HEADLESS=0 to watch the browser for debugging.
_headless = os.getenv("LINKEDIN_HEADLESS", "1") != "0"
_fetcher = (LinkedInBrowserFetcher(_li, _js, headless=_headless)
            if _li and _js else None)
try:
    _model = load_default_model()
except Exception:
    _model = None

app = create_app(hiring_fetcher=_fetcher, embed_model=_model)

__all__ = ["app"]
