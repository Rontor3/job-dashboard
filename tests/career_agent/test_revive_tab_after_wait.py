"""A wait for the human can outlast the browser connection (Mac asleep, lid shut — Opella, live 2026-10-24: Chrome and
the tab lived on, the run's connection died, and a walk on the dead page reported no_advance_control). revive() finds
the same tab by Chrome's own id through a fresh connection, or says it is gone."""
from types import SimpleNamespace as NS

from career_agent.browser.runner import revive


class Dead:
    def __init__(self, browser): self.context = NS(browser=browser)
    def evaluate(self, js): raise RuntimeError("Target page, context or browser has been closed")


def _chrome(tab_ids):
    pages = [NS(url=f"https://x.test/{t}", tid=t) for t in tab_ids]
    ctx = NS(pages=pages, new_cdp_session=lambda pg: NS(send=lambda m: {"targetInfo": {"targetId": pg.tid}}))
    fresh = NS(contexts=[ctx])
    return NS(browser_type=NS(connect_over_cdp=lambda url, timeout=0: fresh)), pages


def test_a_live_page_is_kept():
    live = NS(evaluate=lambda js: 1)
    assert revive(live, "http://localhost:9222", "T1") is live


def test_a_dead_connection_comes_back_on_the_same_tab():
    browser, pages = _chrome(["T0", "T1", "T2"])
    assert revive(Dead(browser), "http://localhost:9222", "T1") is pages[1]


def test_a_tab_that_is_really_gone_is_none():
    browser, _ = _chrome(["T0"])
    assert revive(Dead(browser), "http://localhost:9222", "T1") is None
    assert revive(Dead(browser), None, "T1") is None
