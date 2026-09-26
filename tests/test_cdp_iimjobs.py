import json
from job_dashboard.sources.cdp import iimjobs as im
from job_dashboard.sources.cdp.types import AdapterContext
from tests.cdp_fakes import FakePage, make_session


def item(i, **kw):
    d = {"id": i, "title": "Data Scientist", "jobdesignation": "Senior Data Scientist", "createdTimeMs": 1790139482397,
         "jobDetailUrl": f"https://www.iimjobs.com/j/acme-data-scientist-{i}", "applyStatus": 1, "applyUrl": "",
         "companyData": {"companyName": "Acme"}, "locations": [{"id": 3, "name": "Bangalore"}, {"id": 4, "name": "Pune"}]}
    d.update(kw); return d


def make(pages, details):
    p = FakePage(); p.url = "https://www.iimjobs.com/k/data-scientist-jobs"
    def handler(url, m, h, b):
        assert h == {"version": "2"}          # every call (search and detail) must send the version header
        if "/job/search" in url:
            pg = int(url.split("page=")[1].split("&")[0]); items, more = pages.get(pg, ([], False))
            return 200, json.dumps({"data": [item(**i) if isinstance(i, dict) else item(i) for i in items], "hasMore": more})
        return 200, json.dumps({"data": {"introText": details.get(int(url.split("jobcode=")[1]), "")}})
    p.fetch_handler = handler
    return p


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=["data scientist"], max_pages=3,
                stop_after_known=10**9, hours=72)
    return AdapterContext(**{**base, **kw})


def test_listing_mapping_native_and_external():
    body = {"data": [item(1), item(2, applyStatus=2, applyUrl="https://acme.com/apply")], "hasMore": False}
    cards, more = im.parse_search(body)
    assert more is False
    n, e = im.to_listing(cards[0], "desc"), im.to_listing(cards[1], "desc")
    assert (n.source, n.external_id, n.company, n.location) == ("iimjobs", "1", "Acme", "Bangalore, Pune")
    assert n.job_url == "https://www.iimjobs.com/j/acme-data-scientist-1" and n.apply_kind == "native"
    assert (e.apply_kind, e.apply_url) == ("external", "https://acme.com/apply")
    assert n.posted_date.startswith("2026-")


def test_walks_pages_until_has_more_false_and_fetches_details_for_new():
    p = make({0: ([1, 2], True), 1: ([3], False)}, {1: "<p>one</p>", 2: "<p>two</p>", 3: "<p>three</p>"})
    c = ctx(known=lambda i, u: i == "2")
    with make_session(p) as s:
        out = im.run(s, c)
    assert [(j.external_id, j.description) for j in out] == [("1", "one"), ("3", "three")]
    assert c.stats["skipped_known"] == 1
    assert not any("jobcode=2" in f[0] for f in p.fetches)
    assert "posting=3" in p.fetches[0][0]


def test_backfill_uses_30_day_posting_and_dedupes_across_terms():
    p = make({0: ([1], False)}, {1: "<p>one</p>"})
    with make_session(p) as s:
        out = im.run(s, ctx(mode="backfill", terms=["a", "b"]))
    assert len(out) == 1 and "posting=30" in p.fetches[0][0]


def test_empty_description_skipped_and_cap_partial():
    p = make({0: ([1], False)}, {1: ""})
    c = ctx()
    with make_session(p) as s:
        assert im.run(s, c) == []
    p2 = make({0: ([1, 2], False)}, {1: "<p>x</p>", 2: "<p>y</p>"})
    c2 = ctx()
    with make_session(p2, max_loads=2) as s:                 # goto + search, cap on first detail
        assert im.run(s, c2) == [] and c2.stats["capped"] is True


def test_unsupported_window_rounds_up_to_next_posting_bucket():
    p = make({0: ([1], False)}, {1: "<p>one</p>"})
    with make_session(p) as s:
        im.run(s, ctx(hours=48))
    assert "posting=3" in p.fetches[0][0]


def test_page_filtered_to_nothing_but_has_more_keeps_walking():
    p = make({0: ([{"i": 9, "companyData": {}}], True), 1: ([3], False)}, {3: "<p>three</p>"})
    with make_session(p) as s:
        out = im.run(s, ctx())
    assert [j.external_id for j in out] == ["3"]
