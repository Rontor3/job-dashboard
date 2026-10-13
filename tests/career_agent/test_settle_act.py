"""act(): click once, confirm the page is quiet, report what the click produced."""
import os
import time
from pathlib import Path

import pytest

from career_agent.browser.clicks import act, is_quiet


def _s(**kw):
    base = {"idle": 900, "pending": 0, "busy": False, "n": 1, "ready": "complete"}
    return {**base, **kw}


def test_quiet_needs_no_mutation_no_request_and_no_spinner_in_every_frame():
    assert is_quiet([_s(), _s()])
    assert not is_quiet([_s(), _s(idle=100)])                 # a frame still drawing
    assert not is_quiet([_s(busy=True)])                      # spinner visible
    assert not is_quiet([_s(pending=1)])                      # request in flight
    assert is_quiet([_s(pending=1, idle=5000)])               # long-poll/beacon open but DOM quiet for 5s
    assert not is_quiet([_s(ready="loading")])


def test_act_reports_on_a_page_without_a_watcher_and_clicks_once():
    class P:
        url = "http://a/1"
        def wait_for_timeout(self, ms): pass
        def inner_text(self, sel): return "x"
    clicks = []
    obs = act(P(), lambda: clicks.append(1), max_wait_ms=600)
    assert clicks == [1] and obs.changed is False and obs.page is not None


browser = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="set RUN_BROWSER_TESTS=1 to run")


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page()
        p.goto((Path(__file__).parent / "fixtures" / "settle_act.html").resolve().as_uri())
        yield p
        b.close()


@browser
def test_act_waits_through_the_spinner_until_the_next_step_has_fully_drawn(page):
    obs = act(page, lambda: page.click("#slow"))
    assert obs.changed and obs.stable
    assert page.locator("input[name=phone]").count() == 1      # the LAST part had drawn before act returned


@browser
def test_act_dismisses_a_js_confirm_and_says_so(page):
    obs = act(page, lambda: page.click("#ask"), max_wait_ms=5000)
    assert any(i.startswith("dialog confirm dismissed") for i in obs.intercepts)


@browser
def test_act_continues_on_a_tab_the_click_opened(page):
    obs = act(page, lambda: page.click("#tab"), max_wait_ms=5000)
    assert obs.page is not page and obs.page.url.endswith("#popup")
    assert any(i.startswith("new tab") for i in obs.intercepts)


@browser
def test_a_change_that_is_not_text_is_seen_quickly_not_after_the_full_timeout(page):
    t = time.monotonic()
    obs = act(page, lambda: page.click("#arm"))
    assert obs.changed and page.locator("#send").is_enabled()
    assert time.monotonic() - t < 5                            # was a 25s wait when only body text counted
