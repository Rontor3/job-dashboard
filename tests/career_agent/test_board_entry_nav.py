"""run_board's entry chain + wall gate + page-health loop-top, on a fake tab:
which entry leg clicks, when a wall stops the run (and never reaches perception),
and the one credential-provider pass a wall is allowed."""
from types import SimpleNamespace as NS

import pytest

import career_agent.boards.run as run_mod
from career_agent.browser import page_health
from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import FillDecision


@pytest.fixture(autouse=True)
def _fresh_replays(monkeypatch):
    monkeypatch.setattr(page_health, "_TRIED", set())    # each test gets its own one-replay budget


class FakeLocator:
    """Locators answer `present` by mention: a control is on the page when the
    selector string names it — Playwright's `:has-text('X')` or `#id` alike."""

    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def _control(self):
        return next((c for c in sorted(self.page.present) if c in self.sel), None)

    def filter(self, **k):
        return self

    @property
    def first(self):
        return self

    def is_visible(self):
        return self._control() is not None

    def click(self, **k):
        c = self._control()
        if c is None:
            raise RuntimeError(f"timeout waiting for {self.sel}")     # what Playwright raises on a dead locator
        self.page.clicks.append(c)
        if c in self.page.hops:                                       # a leg that navigates (the handoff legs)
            self.page.url = self.page.hops[c]

    def evaluate(self, js, *a, **k):   # the covered-control fallback: the top element at the click's centre
        self.page.clicks.append(self._control() + ":covered")


class _Ctx:
    """The tab's browser context: pages list + the response listener Capture seams."""

    def __init__(self, *pages):
        self.pages = list(pages)

    def on(self, *a, **k):
        pass

    def remove_listener(self, *a, **k):
        pass


class FakePage:
    """A tab with locatable entry controls. `hops` names which click moves the run
    where (the flow leaving the board, a redirect onto a sign-up wall); `next_hop`
    is where the one bar-style page-health GET lands."""

    def __init__(self, url="https://board.test/job", present=(), hops=None, next_hop=None, bodies=""):
        self.url = url
        self.present = set(present)
        self.hops = hops or {}
        self.context = _Ctx(self)
        self.clicks = []
        self.gotos = []
        self.bodies = bodies                              # everything DOM-y answers empty
        self.frames = []
        self._next = next_hop

    def on(self, *a, **k):
        pass

    def remove_listener(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "Data Scientist | Board"

    def inner_text(self, sel):
        return self.bodies

    def locator(self, sel):
        return FakeLocator(self, sel)

    def goto(self, url, **k):                             # the page-health replay: lands where `_next` says
        self.gotos.append(url)
        self.url = self._next or url
        if self._next is not None:
            self._next = None

    def evaluate(self, js, *a, **k):
        if "hasPw" in js:                                 # classify_entry: no auth shape anywhere
            return {"hasPw": False, "hasEmail": False, "authBtn": False, "verify": False, "fillable": 0}
        if "hasPassword" in js:                           # login-position signals: an ordinary JD page
            return {"hasPassword": False, "hasUser": False, "authControl": False, "credInputs": 0}
        if "document.body" in js:                         # the body-text reads
            return self.bodies
        return ""                                         # structural probes answer empty


class FakeDriver:
    """No fields anywhere (so the run stops 'stuck' after the entry hop). Perception
    calls are logged — the wall tests use the log to prove what was never read."""
    ask_optional_upfront = False

    def __init__(self):
        self.saw_urls = []

    def fields(self, page, board, ctx, cap):
        self.saw_urls.append(page.url)
        return []

    def prefill(self, board, cap):
        return {}

    def put(self, page, board, ctx, fields, decisions):
        pass

    def next_control(self, page, board, ctx):
        return None

    def click(self, page, label, ctx):
        pass


class BouncingDriver(FakeDriver):
    """One required field (answered by the tier patch), then a Continue control
    whose click redirects the run onto the sign-up wall."""

    def __init__(self, wall_url):
        super().__init__()
        self.wall_url, self._advanced = wall_url, False

    def fields(self, page, board, ctx, cap):
        self.saw_urls.append(page.url)
        return [Field("ctc", "text", "Expected CTC", True)]

    def next_control(self, page, board, ctx):
        return None if self._advanced else ("Continue", False)

    def click(self, page, label, ctx):
        self._advanced = True
        page.clicks.append(label)
        page.url = self.wall_url                          # the Continue click bounced: /candidates/register/


class FakeAssist:
    """On its first call it clicks `selector` and says it acted; afterwards it gives up."""

    def __init__(self, selector):
        self.selector, self.reasons = selector, []

    def recover(self, page, reason):
        self.reasons.append(reason)
        if len(self.reasons) > 1:
            return False
        page.locator(self.selector).click()
        return True


class Provider:
    """The credential provider seam: called once with (page, gate, site)."""

    def __init__(self, clear_to=None):
        self.calls, self.clear_to = [], clear_to

    def __call__(self, page, gate, site):
        self.calls.append((gate, site, page.url))
        if self.clear_to:
            page.url = self.clear_to                      # guest apply / register landed somewhere real


def _board(**kw):
    b = {"id": "board:test", "archetype": "form", "entry": {"selector": "#apply", "submits": "no"},
         "confirm": [], "advance": ["Next"], "final": ["Submit application"],
         "challenge": ["verify you are human"], "logged_out": [], "interstitial": [], "daily_cap": 5}
    return {**b, **kw}


def _run(page, board, monkeypatch, driver=None, answer=None, **ctx):
    monkeypatch.setattr("career_agent.browser.clicks.wait_until_stable", lambda page: True)
    monkeypatch.setattr(run_mod, "answer_fields",
                        answer or (lambda fields, c: ([], list(fields))))
    driver = driver or FakeDriver()
    monkeypatch.setitem(run_mod.DRIVERS, "form", driver)
    out = run_mod.run_board(page, board, {"deps": NS(snapshot=lambda p: []),
                                          "human": NS(collect=lambda fields: {}),
                                          "profile": None, "intended_url": "https://board.test/job", **ctx})
    return out, page, driver


def _answered(fields, c):
    return ([FillDecision(f.ref, f.kind, f.label, "30", "fill", "profile") for f in fields], [])


def test_entry_chain_clicks_the_first_leg_present_on_the_page(monkeypatch):
    pg = FakePage(present=("#leg2",))
    board = _board(entry={"submits": "no", "chain": [
        {"selector": "#leg1", "leg": "native"}, {"selector": "#leg2", "leg": "button"}]})
    out, pg, _ = _run(pg, board, monkeypatch)
    assert out["entry"] == {"leg": "button"} and pg.clicks == ["#leg2"]
    assert out["stopped_reason"] == "stuck"               # the run carried on past the entry click


def test_entry_chain_falls_through_to_the_external_leg_and_stops_left_board(monkeypatch):
    # Indeed external jobs: the native legs are absent; "Apply on company site" wins,
    # the run leaves the board and the career-site engine continues (existing handoff).
    pg = FakePage(present=("Apply on company site",),
                  hops={"Apply on company site": "https://company.test/careers/apply"})
    board = _board(domains=["board.test"], entry={"submits": "no", "chain": [
        {"selector": "#indeedApplyButton", "leg": "native"},
        {"selector": "button:has-text('Apply now')", "leg": "native"},
        {"selector": "a:has-text('Apply on company site')", "leg": "external", "handoff": "external"}]})
    out, pg, _ = _run(pg, board, monkeypatch)
    assert out["stopped_reason"] == "left_board" and out["url"].startswith("https://company.test/")
    assert out["entry"] == {"leg": "external"} and pg.clicks == ["Apply on company site"]


def test_entry_chain_exhausted_keeps_no_entry_and_assist_recover(monkeypatch):
    pg = FakePage(present=())
    board = _board(entry={"submits": "no", "chain": [
        {"selector": "#gone1", "leg": "native"}, {"selector": "#gone2", "leg": "native"}]})
    out, pg, _ = _run(pg, board, monkeypatch)
    assert out["stopped_reason"] == "no_entry" and "entry" not in out
    assert out["error"] == "no entry leg on the page" and pg.clicks == []
    assist = FakeAssist("#rescue")
    pg2 = FakePage(present=("#rescue",))
    out2, _, _ = _run(pg2, board, monkeypatch, assist=assist)
    # the assist's recovery click is not a chain leg: no `entry` is claimed for it
    assert assist.reasons[0] == "no_entry" and out2["stopped_reason"] == "stuck"
    assert "entry" not in out2 and "#rescue" in pg2.clicks


def test_a_leg_covered_by_an_overlay_still_clicks_through_the_fallback(monkeypatch):
    pg = FakePage(present=("#hop",))
    board = _board(entry={"submits": "no", "chain": [{"selector": "#hop", "leg": "native"}]})

    def click(self, **k):                                  # Playwright: intercepted by the overlay above
        raise RuntimeError("intercepts pointer events")
    monkeypatch.setattr(FakeLocator, "click", click)
    out, pg, _ = _run(pg, board, monkeypatch)
    assert pg.clicks == ["#hop:covered"] and out["entry"] == {"leg": "native"}
    assert out["stopped_reason"] == "stuck"


def test_a_board_whose_entry_has_no_chain_behaves_exactly_as_before(monkeypatch):
    pg = FakePage(present=("#apply",))
    out, pg, _ = _run(pg, _board(), monkeypatch)
    assert out.get("entry") == {"leg": "selector"} and pg.clicks == ["#apply"]
    assert out["stopped_reason"] == "stuck"
    gone = FakePage(present=())
    out2, _, _ = _run(gone, _board(), monkeypatch)
    assert out2["stopped_reason"] == "no_entry" and gone.clicks == [] and out2["error"]


def test_a_run_landing_on_chromes_error_page_gets_one_fresh_reload(monkeypatch):
    # the loop-top page-health check: one bar-style GET of the intended URL, then carry on
    pg = FakePage("chrome-error://chromewebdata/", present=("#apply",), next_hop="https://board.test/job")
    out, pg, _ = _run(pg, _board(), monkeypatch)
    assert out["stopped_reason"] == "stuck" and pg.gotos == ["https://board.test/job"]


def test_a_page_that_fails_again_after_the_replay_stops_dead_page(monkeypatch):
    pg = FakePage("chrome-error://chromewebdata/", present=("#apply",), next_hop="chrome-error://chromewebdata/")
    out, pg, _ = _run(pg, _board(), monkeypatch)
    assert out["stopped_reason"] == "dead_page" and pg.gotos == ["https://board.test/job"]


WALL_URL = "https://www.instahyre.com/candidates/register/"


def test_a_sign_up_wall_never_reaches_perception_and_walls_without_a_provider(monkeypatch):
    # job 30076: click Apply -> the site bounces to /candidates/register/; nothing there is read
    pg = FakePage(present=("#apply",), hops={"#apply": WALL_URL})
    driver = FakeDriver()
    out, pg, driver = _run(pg, _board(), monkeypatch, driver=driver)
    assert out["stopped_reason"] == "auth_wall" and out["pending_human"] == []
    assert out["entry"] == {"leg": "selector"}                       # the entry click itself was fine
    assert driver.saw_urls == []                                     # perception never ran on the wall


def test_the_wall_taps_the_credential_provider_once_and_stops_when_it_cannot_clear(monkeypatch):
    pg = FakePage(present=("#apply",), hops={"#apply": WALL_URL})
    provider = Provider()                                            # the provider ran but the wall stands
    out, pg, _ = _run(pg, _board(), monkeypatch, cred_provider=provider)
    assert out["stopped_reason"] == "auth_wall"
    site, wall = provider.calls[0][1], provider.calls[0][2]          # provider ran exactly once, on the wall
    assert site == "www.instahyre.com" and wall == WALL_URL


def test_the_provider_clears_the_wall_and_the_run_continues(monkeypatch):
    pg = FakePage(present=("#apply",), hops={"#apply": WALL_URL})
    provider = Provider(clear_to="https://www.instahyre.com/jobs")   # guest apply / register landed real
    driver = FakeDriver()
    out, pg, driver = _run(pg, _board(), monkeypatch, driver=driver, cred_provider=provider)
    assert out["stopped_reason"] == "stuck" and len(provider.calls) == 1
    assert all(u != WALL_URL for u in driver.saw_urls)               # only the cleared page was ever read


def test_a_wall_after_form_work_is_just_a_stop(monkeypatch):
    # the run already filled a field and clicked its way onto the wall: no rewinding
    # into an account flow — the provider is not called, the stop is as before
    pg = FakePage(present=("#apply",), hops={"next": WALL_URL})
    provider = Provider()
    driver = BouncingDriver(WALL_URL)
    out, pg, _ = _run(pg, _board(), monkeypatch, driver=driver, answer=_answered, cred_provider=provider)
    assert out["stopped_reason"] == "auth_wall" and provider.calls == []
    assert out["decisions"] and driver.saw_urls[-1] != WALL_URL      # what was filled stays recorded
