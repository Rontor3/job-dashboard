import json

import pytest

from job_dashboard.sources.cdp import ycstartups as yc
from job_dashboard.sources.cdp.types import AdapterContext, CapReached
from tests.cdp_fakes import FakePage, make_session


def card(i, title="Data Scientist", company="Acme", location="Bengaluru, KA, IN", **kw):
    d = dict(id=i, title=title, jobType="Full-time", location=location, roleType="Data science",
             salary="$100K", companyName=company, companySlug="acme", companyBatch="W20",
             companyOneLiner="one liner", companyLogoUrl="https://x/logo.png", companyLastActiveAt=None,
             applyUrl=f"https://account.ycombinator.com/authenticate?signup_job_id={i}")
    d.update(kw)
    return d


def search(term, cards):
    url = yc.search_url(term)
    return {url: [(url, {"jobs": cards})]}


def _double_escape(description_html):
    """Mirrors the real page: JSON-escaped (with < > as \\u003c \\u003e, matching Next's flight
    protocol), then that whole blob is HTML-attribute-escaped a second time."""
    js = json.dumps(description_html)[1:-1].replace("<", "\\u003c").replace(">", "\\u003e")
    return js.replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#39;")


def detail(job_id, paragraphs):
    """`paragraphs` are plain text; joined as real <p> tags, then embedded the way the live page does."""
    description_html = "".join(f"<p>{p}</p>\n" for p in paragraphs).rstrip("\n")
    blob = _double_escape(description_html)
    url = yc.job_url(job_id)
    html = f'<html><body><script data-props="{{&quot;descriptionHtml&quot;:&quot;{blob}&quot;,&quot;next&quot;:1}}"></script></body></html>'
    return {url: [(url, html)]}


def script(*parts):
    out = {}
    for p in parts:
        out.update(p)
    return out


def ctx(known=(), terms=("data scientist",)):
    return AdapterContext(mode="incremental", known=lambda i, u: i in known, terms=list(terms),
                          max_pages=1, stop_after_known=10**9, hours=48)


def run(page, c, **kw):
    with make_session(page, **kw) as s:
        return yc.run(s, c)


def test_search_url_biases_toward_india_and_has_no_pagination_param():
    u = yc.search_url("ai engineer")
    assert u == "https://www.workatastartup.com/jobs/search?q=ai+engineer+india"
    assert "page" not in u and "offset" not in u


def test_parse_search_drops_incomplete_rows():
    cards = yc.parse_search({"jobs": [card(1), {"title": "no id"}, card(2, title="")]})
    assert [c["id"] for c in cards] == [1]


def test_parse_detail_decodes_the_double_escaped_description():
    html = detail(1, ["About Acme", "About the role: build models", "We're hiring", "Python, PyTorch"])[yc.job_url(1)][0][1]
    assert yc.parse_detail(html) == "About Acme\nAbout the role: build models\nWe're hiring\nPython, PyTorch"
    assert yc.parse_detail("<html><body>no descriptionHtml key here</body></html>") is None
    assert yc.parse_detail('&quot;descriptionHtml&quot;:&quot;bad \\x escape&quot;,&quot;x&quot;:1') is None


def test_to_listing_never_stores_the_stale_apply_url_and_has_no_date():
    c = yc.parse_search({"jobs": [card(66043)]})[0]
    j = yc.to_listing(c, "full description")
    assert (j.source, j.external_id, j.job_url) == ("ycstartups", "66043", "https://www.workatastartup.com/jobs/66043")
    assert j.apply_kind == "native" and j.apply_url is None and j.posted_date is None
    assert j.company == "Acme" and j.location == "Bengaluru, KA, IN" and j.description == "full description"


def test_new_job_gets_queued_and_detailed():
    page = FakePage(script(search("data scientist", [card(1)]), detail(1, ["About the role: build models"])))
    out = run(page, ctx())
    assert [j.external_id for j in out] == ["1"] and out[0].description == "About the role: build models"


def test_known_job_is_skipped_without_a_detail_load():
    page = FakePage(script(search("data scientist", [card(1), card(2)]), detail(2, ["d"])))
    c = ctx(known={"1"})
    out = run(page, c)
    assert [j.external_id for j in out] == ["2"] and c.stats["skipped_known"] == 1


def test_off_target_title_never_gets_a_detail_load():
    page = FakePage(script(search("data scientist", [card(1, title="Chip Conveyor Service Engineer")])))
    c = ctx()
    assert run(page, c) == [] and c.stats["off_target"] == 1


def test_duplicate_ids_across_terms_collapse():
    page = FakePage(script(search("data scientist", [card(1)]), search("ai engineer", [card(1)]), detail(1, ["d"])))
    out = run(page, ctx(terms=("data scientist", "ai engineer")))
    assert len(out) == 1


def test_missing_description_is_skipped_not_known():
    url = yc.job_url(1)
    page = FakePage(script(search("data scientist", [card(1)]), {url: [(url, "<html>nothing</html>")]}))
    c = ctx()
    assert run(page, c) == [] and c.stats["skipped_known"] == 0


def test_no_results_is_not_blocked():
    page = FakePage(script(search("data scientist", [])))
    assert run(page, ctx()) == []


def test_cap_returns_partial_and_sets_capped():
    page = FakePage(script(search("data scientist", [card(1)]), detail(1, ["d"])))
    c = ctx()
    out = run(page, c, max_loads=1)          # only the search load fits
    assert out == [] and c.stats["capped"] is True
