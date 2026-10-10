"""Hiring-post search through the agent's isolated, logged-in Chrome over CDP (no cookies
in .env). Same ``search_posts(keyword)`` contract as ``LinkedInBrowserFetcher``,
same parser; each keyword opens its own tab via ``CdpSession`` and closes it."""
from __future__ import annotations

import random
import time
import urllib.parse

from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.linkedin.post_parse import parse_posts_html
from job_dashboard.sources.cdp.runner import CDP_URL
from job_dashboard import agent_browser
from job_dashboard.sources.cdp.session import CdpSession
from job_dashboard.sources.cdp.types import Blocked


class CdpHiringFetcher:
    def __init__(self, cdp_url=CDP_URL, *, scrolls=4, session_factory=None, nap=None):
        self.cdp_url, self._scrolls = cdp_url, scrolls
        self._session = session_factory or (lambda: CdpSession(cdp_url, max_loads=1))
        self._nap = nap or (lambda: time.sleep(random.uniform(6, 12)))
        self._calls = 0

    def search_posts(self, keyword, *, date_posted="past-24h"):
        problem = agent_browser.ensure_running(self.cdp_url)
        if problem:
            raise LinkedInAuthError(problem)
        if self._calls:
            self._nap()                      # pace keywords like a person would
        self._calls += 1
        url = ("https://www.linkedin.com/search/results/content/"
               f"?keywords={urllib.parse.quote(keyword)}&datePosted=%22{date_posted}%22"
               "&origin=FACETED_SEARCH")
        try:
            with self._session() as s:
                s.goto(url)
                s.scroll(self._scrolls)
                return parse_posts_html(s.html())
        except Blocked as e:
            raise LinkedInAuthError(f"LinkedIn blocked/logged out in the agent browser — log in there and retry ({e})")
