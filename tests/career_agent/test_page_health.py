"""page_health: chrome-error detection + the one-replay rule, on fake tabs."""
from types import SimpleNamespace as NS

import pytest

from career_agent.browser import page_health


class FakePage:
    """A tab: `url` + a visible body; `goto` may land somewhere real or re-fail."""

    def __init__(self, url, bodies=""):
        self.url = url
        self.bodies = bodies
        self.frames = []
        self.gotos = []
        self._next = None                            # (url, bodies) ONE fresh goto ends on

    def goto(self, url, **k):
        self.gotos.append(url)
        if self._next is not None:
            self.url, self.bodies = self._next
            self._next = None
        else:
            self.url = url                           # the bar-GET stayed on the error, as per the bodies

    def evaluate(self, js, *a, **k):
        return self.bodies                           # the body-read JS sees the visible text

    def inner_text(self, sel):
        return self.bodies

    def wait_for_timeout(self, ms):
        pass


@pytest.fixture(autouse=True)
def _one_run(monkeypatch):
    monkeypatch.setattr(page_health, "_TRIED", set())
    from career_agent.browser import clicks
    monkeypatch.setattr(clicks, "wait_until_stable", lambda page: True)


def test_chrome_error_reads_the_url_then_the_body():
    assert page_health.chrome_error(FakePage("chrome-error://chromewebdata/")) == "chrome-error"
    assert page_health.chrome_error(FakePage("https://x/job/", bodies="ERR_CACHE_MISS")) == "ERR_CACHE_MISS"
    assert page_health.chrome_error(FakePage("https://x/job/")) is None


def test_a_healthy_page_needs_no_recovery():
    assert page_health.recover(FakePage("https://x/job/"), "https://x/job/") is None
    assert page_health.recover(FakePage("about:blank"),
                               "") is None               # no intended url: nothing to replay


def test_recover_replays_the_intended_url_once():
    pg = FakePage("chrome-error://chromewebdata/")
    pg._next = ("https://deloitte.test/job/", "")
    pg.bodies = ""                                       # evaluate reads the LIVE body
    recovered = page_health.recover(pg, "https://deloitte.test/job/")
    assert recovered == "recovered"
    assert pg.gotos == ["https://deloitte.test/job/"] and pg.url == "https://deloitte.test/job/"


def test_a_second_failure_of_the_same_pair_is_dead_and_never_replayed():
    # the fresh GET lands the tab back on the same error: that pair is done after one replay
    pg = FakePage("chrome-error://chromewebdata/", bodies="ERR_CACHE_MISS")
    pg._next = ("chrome-error://chromewebdata/", "ERR_CACHE_MISS")
    assert page_health.recover(pg, "https://x/job/") == "dead"
    assert page_health.recover(pg, "https://x/job/") == "dead"
    assert pg.gotos == ["https://x/job/"]                           # exactly one replay: no loop


def test_a_goto_that_throws_is_dead():
    pg = FakePage("chrome-error://chromewebdata/")
    pg.goto = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("closed"))
    assert page_health.recover(pg, "https://x/job/") == "dead"


def test_a_fresh_signature_after_repair_earns_its_own_replay():
    # ERR_CACHE_MISS was replayed and fixed the tab; later the same page surfaces a
    # different failure (e.g. ERR_NAME_NOT_RESOLVED): that pair is new, one more GET.
    pg = FakePage("https://x/job/", bodies="ERR_CACHE_MISS")
    pg._next = ("https://x/job/?fresh=1", "")
    assert page_health.recover(pg, "https://x/job/") == "recovered"
    pg.bodies = "ERR_NAME_NOT_RESOLVED"
    pg._next = ("https://x/job/?fresh=2", "")
    assert page_health.recover(pg, "https://x/job/") == "recovered"
    assert len(pg.gotos) == 2
