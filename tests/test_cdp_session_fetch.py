import gzip, json
import pytest
from job_dashboard.sources.cdp.types import Blocked, CapReached, html_to_text
from tests.cdp_fakes import FakePage, FakeRequest, make_session


def page_with(handler, url="https://www.instahyre.com/x"):
    p = FakePage(); p.fetch_handler = handler; p.url = url
    return p


def test_fetch_returns_text_and_resolves_relative_url():
    p = page_with(lambda u, m, h, b: (200, '{"ok": 1}'))
    with make_session(p) as s:
        assert s.fetch("/api/v1/job_search?x=1", hosts=("www.instahyre.com",)) == '{"ok": 1}'
    assert p.fetches == [("https://www.instahyre.com/api/v1/job_search?x=1", "GET", {}, None)]


def test_fetch_rejects_foreign_host_without_calling():
    p = page_with(lambda u, m, h, b: (200, ""))
    with make_session(p) as s:
        with pytest.raises(ValueError):
            s.fetch("https://evil.example/x", hosts=("www.instahyre.com",))
    assert p.fetches == []


@pytest.mark.parametrize("status", [401, 403, 404, 406, 429, 500])
def test_any_non_200_is_blocked(status):
    with make_session(page_with(lambda u, m, h, b: (status, "no"))) as s:
        with pytest.raises(Blocked):
            s.fetch("/a", hosts=("www.instahyre.com",))


def test_fetch_counts_toward_cap_and_naps():
    naps, p = [], page_with(lambda u, m, h, b: (200, "x"))
    from job_dashboard.sources.cdp.session import CdpSession
    with CdpSession("u", max_loads=2, nap=lambda: naps.append(1), connect=lambda u: (p, lambda: None)) as s:
        s.fetch("/a", hosts=("www.instahyre.com",)); s.fetch("/b", hosts=("www.instahyre.com",))
        with pytest.raises(CapReached):
            s.fetch("/c", hosts=("www.instahyre.com",))
    assert naps == [1]


def test_exchanges_parse_json_and_gzip_request_bodies():
    body = json.dumps({"operationName": "JobSearchResultsX"}).encode()
    req = FakeRequest("https://wellfound.com/graphql", {"x-apollo-signature": "sig"}, gzip.compress(body))
    p = FakePage({"https://a/": [("https://wellfound.com/graphql", {"data": 1}, req)]})
    with make_session(p) as s:
        with s.capture("graphql") as cap:
            s.goto("https://a/")
    assert list(cap.exchanges()) == [({"x-apollo-signature": "sig"}, {"operationName": "JobSearchResultsX"}, {"data": 1})]


def test_html_to_text():
    assert html_to_text("<p>Build <b>models</b></p><ul><li>Python</li></ul>&amp; more") == "Build models\nPython\n& more"
