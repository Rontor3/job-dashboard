from career_agent.browser.clicks import click_and_settle, pace, page_signature


class FakePage:
    def __init__(self):
        self.url, self.waits, self.body = "http://x/1", [], "one"
    def wait_for_timeout(self, ms): self.waits.append(ms)
    def inner_text(self, sel): return self.body
    def wait_for_load_state(self, *a, **k): pass


def test_pace_keeps_a_minimum_gap_between_clicks():
    pg = FakePage()
    pace(pg, 300)                       # first click on this page: no wait
    assert pg.waits == []
    pace(pg, 300)
    assert pg.waits and 250 <= pg.waits[0] <= 300              # the second one waited out the gap


def test_a_click_is_made_once_and_the_page_is_waited_on():
    pg, clicks = FakePage(), []

    def do_click():
        clicks.append(1)
        pg.url = "http://x/2"          # the page responded

    click_and_settle(pg, do_click)
    assert clicks == [1] and page_signature(pg)[0] == "http://x/2"


def test_a_failed_wait_never_causes_a_second_click():
    pg, clicks = FakePage(), []
    pg.wait_for_load_state = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("page closed"))
    click_and_settle(pg, lambda: clicks.append(1))
    assert clicks == [1]


def test_tab_ledger_closes_what_the_run_opened_and_never_the_users_tabs():
    from career_agent.browser.runner import TabLedger

    class Pg:
        def __init__(self, url): self.url, self.closed = url, False
        def is_closed(self): return self.closed
        def close(self): self.closed = True

    class Ctx:
        def __init__(self): self.cb = None
        def on(self, ev, cb): self.cb = cb

    ctx = Ctx()
    work, users, popup, facebook, final = Pg("https://jd"), Pg("https://users-own"), Pg("https://popup"), Pg("https://facebook.com/x"), Pg("https://form")
    led = TabLedger(ctx, work)
    led.mark_user_owned(users); led.opened.append(users)
    for p in (popup, facebook, final):
        ctx.cb(p)
    led.close_all_but(keep=[final])
    assert [p.closed for p in (work, users, popup, facebook, final)] == [True, False, True, True, False]
    # the tab a result points at survives even when it is not the variable we kept
    a, b = Pg("https://a"), Pg("https://b#step2")
    led2 = TabLedger(ctx, a); ctx.cb(b)
    led2.close_all_but(keep=[], keep_urls=["https://b"])
    assert a.closed and not b.closed


def test_a_single_page_app_that_changes_url_first_is_waited_on_until_its_content_is_drawn():
    from career_agent.browser.clicks import settle_after_click

    class SpaPage(FakePage):
        """URL changes at once; the old text stays for 1.5s (loading), then the new step's text appears and settles."""
        def __init__(self):
            super().__init__(); self.t = 0.0; self.url = "http://x/questions"
        def wait_for_timeout(self, ms): self.t += ms / 1000
        def inner_text(self, sel): return "Add a resume" if self.t < 1.5 else "Answer these questions"

    pg = SpaPage()
    before = ("http://x/resume", hash("Add a resume"))
    settle_after_click(pg, before, quiet_ms=0)
    assert pg.inner_text("body") == "Answer these questions"
    assert pg.t >= 1.5 + 1.2 - 0.3                                   # waited for the new text AND for it to stop changing


def test_wait_for_change_gives_a_slow_page_more_time_and_reports_whether_it_changed():
    from career_agent.browser.clicks import wait_for_change

    class Slow(FakePage):
        def __init__(self, change_at): super().__init__(); self.t, self.change_at = 0.0, change_at
        def wait_for_timeout(self, ms): self.t += ms / 1000
        def inner_text(self, sel): return "old" if self.t < self.change_at else "new"

    assert wait_for_change(Slow(4.0), (FakePage().url, hash("old"))) is True            # arrives after 4s: waited for
    assert wait_for_change(Slow(99.0), (FakePage().url, hash("old")), max_wait_ms=3000) is False   # never changes
