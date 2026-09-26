import pytest
from job_dashboard.sources.cdp.types import Blocked, CapReached
from tests.cdp_fakes import FakePage, make_session


def test_captures_only_matching_responses_and_skips_bad_json():
    page = FakePage({"https://a/": [("https://x/voyagerJobsDashJobCards?q", {"n": 1}),
                                     ("https://x/other", {"n": 2}),
                                     ("https://x/voyagerJobsDashJobCards?bad", ValueError("no json"))]})
    with make_session(page) as s:
        with s.capture("voyagerJobsDashJobCards") as cap:
            s.goto("https://a/")
    assert [b for _, b in cap.bodies()] == [{"n": 1}]
    assert page.handlers == []          # listener removed on exit


def test_closes_only_own_tab_and_detaches():
    page = FakePage()
    s = make_session(page)
    with s:
        pass
    assert page.closed and s.closed == [1]


def test_cap_reached_after_max_loads():
    with make_session(FakePage(), max_loads=2) as s:
        s.goto("https://a/1"); s.goto("https://a/2")
        with pytest.raises(CapReached):
            s.goto("https://a/3")


@pytest.mark.parametrize("kw", [
    dict(status=403), dict(status=429), dict(text="We noticed unusual activity from your account"),
])
def test_blocked_signals(kw):
    with make_session(FakePage(**kw)) as s:
        with pytest.raises(Blocked):
            s.goto("https://a/")


def test_blocked_on_login_redirect():
    with make_session(FakePage()) as s:
        with pytest.raises(Blocked):
            s.goto("https://www.linkedin.com/authwall?trk=x")


def test_naps_between_loads_but_not_before_the_first():
    from job_dashboard.sources.cdp.session import CdpSession
    naps, page = [], FakePage()
    with CdpSession("u", max_loads=9, nap=lambda: naps.append(1),
                    connect=lambda u: (page, lambda: None)) as s:
        s.goto("https://a/1"); s.goto("https://a/2"); s.goto("https://a/3")
    assert naps == [1, 1]
