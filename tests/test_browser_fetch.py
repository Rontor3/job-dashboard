import pytest
from job_dashboard.linkedin.browser_fetch import (
    LinkedInBrowserFetcher, LinkedInAuthError,
)

CARD = """
<div data-view-name="feed-full-update" data-urn="urn:li:activity:1">
  <span class="update-components-actor__title"><span>Jane Doe</span></span>
  <span class="update-components-actor__description">EM @ Acme</span>
  <div class="update-components-text">Hiring an ML Engineer!</div>
</div>"""


class FakeDriver:
    def __init__(self, page_source, current_url="https://www.linkedin.com/search/results/content/"):
        self.page_source = page_source
        self.current_url = current_url
        self.calls = []
    def get(self, url): self.calls.append(("get", url))
    def add_cookie(self, c): self.calls.append(("cookie", c["name"]))
    def execute_script(self, *a, **k): self.calls.append(("scroll",))
    def quit(self): self.calls.append(("quit",))


def _fetcher(driver):
    return LinkedInBrowserFetcher(
        "LIAT", "ajax:1",
        driver_factory=lambda: driver,
        sleep=lambda *_: None,          # no real delays in tests
        max_scrolls=2,
    )


def test_search_returns_parsed_posts_and_injects_cookies():
    d = FakeDriver(CARD)
    posts = _fetcher(d).search_posts("hiring ML engineer")
    assert len(posts) == 1 and posts[0]["poster_name"] == "Jane Doe"
    # cookies injected and driver cleaned up
    assert ("cookie", "li_at") in d.calls and ("cookie", "JSESSIONID") in d.calls
    assert ("quit",) in d.calls


def test_login_redirect_raises_auth_error():
    d = FakeDriver("<html>Sign in</html>", current_url="https://www.linkedin.com/login")
    with pytest.raises(LinkedInAuthError):
        _fetcher(d).search_posts("hiring ML engineer")
    assert ("quit",) in d.calls           # still cleaned up on error


def test_driver_always_quit_even_if_parse_empty():
    d = FakeDriver("<html>no cards</html>")
    assert _fetcher(d).search_posts("x") == []
    assert ("quit",) in d.calls
