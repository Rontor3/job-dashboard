import pytest

from job_dashboard.linkedin import cdp_fetch
from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
from job_dashboard.sources.cdp.types import Blocked

CARD = ('<div role="listitem"><img alt="View Jane Doe\'s profile"><a href="https://www.linkedin.com/in/jane/">J</a>'
        "Jane Doe • 3rd+ Head of AI at Acme 5h We are hiring an ML Engineer in Bengaluru, mail jobs@acme.ai</div>")


class FakeSession:
    def __init__(self, html="", block=False):
        self.html_, self.block, self.urls, self.scrolled = html, block, [], 0

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def goto(self, url):
        if self.block:
            raise Blocked("authwall")
        self.urls.append(url)

    def scroll(self, n): self.scrolled = n
    def html(self): return self.html_


@pytest.fixture(autouse=True)
def _reachable(monkeypatch):
    monkeypatch.setattr(cdp_fetch, "cdp_reachable", lambda url: True)


def test_search_posts_parses_cards_from_cdp_tab():
    s = FakeSession(CARD)
    naps = []
    f = cdp_fetch.CdpHiringFetcher(session_factory=lambda: s, nap=lambda: naps.append(1), scrolls=2)
    posts = f.search_posts("hiring ML engineer")
    assert posts and posts[0]["poster_name"] == "Jane Doe" and "jobs@acme.ai" in posts[0]["text"]
    assert "keywords=hiring%20ML%20engineer" in s.urls[0] and s.scrolled == 2
    f.search_posts("again")
    assert naps == [1]                        # paced between keywords, not before the first


def test_blocked_becomes_auth_error():
    f = cdp_fetch.CdpHiringFetcher(session_factory=lambda: FakeSession(block=True), nap=lambda: None)
    with pytest.raises(LinkedInAuthError):
        f.search_posts("x")


def test_unreachable_chrome_is_auth_error(monkeypatch):
    monkeypatch.setattr(cdp_fetch, "cdp_reachable", lambda url: False)
    with pytest.raises(LinkedInAuthError, match="CDP"):
        cdp_fetch.CdpHiringFetcher().search_posts("x")
