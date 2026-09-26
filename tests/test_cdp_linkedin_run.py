# tests/test_cdp_linkedin_run.py
import pytest
from job_dashboard.sources.cdp import linkedin as li
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, make_session

CARD_URL = "https://x/voyager/api/voyagerJobsDashJobCards?q=1"
DET_URL = "https://x/voyager/api/graphql?queryId=jobPostingDetailDescription"


def card(i, easy=False):
    return {"$type": "a.JobPostingCard", "jobPostingUrn": f"urn:li:fsd_jobPosting:{i}", "jobPostingTitle": f"T{i}",
            "primaryDescription": {"text": "Co"}, "footerItems": [{"type": "LISTED_DATE", "timeAt": 1790000000000}]
            + ([{"type": "EASY_APPLY_TEXT"}] if easy else [])}


def det(i, text="desc"):
    return {"$type": "a.JobDescription", "entityUrn": f"urn:li:fsd_jobPosting:{i}", "descriptionText": {"text": text}}


def ctx(known=(), **kw):
    base = dict(mode="incremental", known=lambda i, u: i in known, terms=["ml"], max_pages=2, stop_after_known=3)
    return AdapterContext(**{**base, **kw})


def page_for(term_pages, details=(), view=None):
    script = {}
    for url, ids in term_pages.items():
        script[url] = [(CARD_URL, {"included": [card(i) for i in ids]}), (DET_URL, {"included": [det(i) for i in details]})]
    for i, body in (view or {}).items():
        script[li.job_url(i)] = [(DET_URL, {"included": body})]
    return FakePage(script)


def test_new_jobs_use_prefetched_description_and_skip_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1", "2"], li.search_url("ml", 48, start=50): []}, details=["1", "2"])
    c = ctx(known={"2"})
    with make_session(page) as s:
        out = li.run(s, c)
    assert [j.external_id for j in out] == ["1"] and c.stats["skipped_known"] == 1
    assert page.visited == [u0, li.search_url("ml", 48, start=50)]      # no detail loads


def test_stops_term_after_n_consecutive_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1", "2", "3", "4"]}, details=[])
    c = ctx(known={"1", "2", "3", "4"}, stop_after_known=3)
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert page.visited == [u0]                                           # page 2 never loaded


def test_card_without_prefetch_gets_detail_load():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=50): []}, details=[],
                    view={"9": [det("9", "from view page")]})
    with make_session(page) as s:
        out = li.run(s, ctx())
    assert out[0].description == "from view page" and li.job_url("9") in page.visited


def test_card_with_no_description_anywhere_is_skipped_not_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=50): []}, details=[])
    c = ctx()
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert c.stats["skipped_known"] == 0


def test_backfill_uses_30_day_window_and_no_early_stop():
    u = li.search_url("ml", 720)
    page = page_for({u: ["1", "2", "3", "4"], li.search_url("ml", 720, start=50): []}, details=["1"])
    c = ctx(mode="backfill", known={"1", "2", "3", "4"}, stop_after_known=3)
    with make_session(page) as s:
        li.run(s, c)
    assert len(page.visited) == 2


def test_blocked_propagates_and_cap_returns_partial():
    with make_session(FakePage(status=429)) as s:
        with pytest.raises(Blocked):
            li.run(s, ctx())
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1"]}, details=["1"])
    with make_session(page, max_loads=1) as s:
        assert [j.external_id for j in li.run(s, ctx())] == ["1"]         # cap hit on page 2, keeps page 1


def test_same_job_from_two_terms_collapses():
    pages = {li.search_url(t, 48): ["1"] for t in ("a", "b")}
    pages.update({li.search_url(t, 48, start=50): [] for t in ("a", "b")})
    with make_session(page_for(pages, details=["1"])) as s:
        assert len(li.run(s, ctx(terms=["a", "b"]))) == 1


def test_cap_marks_ctx_capped():
    page = page_for({li.search_url("ml", 48): ["1"]}, details=["1"])
    c = ctx()
    with make_session(page, max_loads=1) as s:
        li.run(s, c)
    assert c.stats["capped"] is True


def test_detail_loads_run_after_all_search_pages_round_robin():
    a, b = li.search_url("a", 48), li.search_url("b", 48)
    pages = {a: ["1", "2"], b: ["3"], li.search_url("a", 48, start=50): [], li.search_url("b", 48, start=50): []}
    view = {i: [det(i)] for i in "123"}
    page = page_for(pages, details=[], view=view)
    with make_session(page) as s:
        out = li.run(s, ctx(terms=["a", "b"]))
    assert len(out) == 3
    searches = [u for u in page.visited if "/search/" in u]
    assert page.visited[:len(searches)] == searches                       # all searches first
    assert page.visited[len(searches):] == [li.job_url("1"), li.job_url("3"), li.job_url("2")]


def test_budget_exhausted_by_details_still_searches_every_term():
    a, b = li.search_url("a", 48), li.search_url("b", 48)
    page = page_for({a: ["1", "2", "3"], b: ["4"]}, details=[], view={"4": [det("4")]})
    with make_session(page, max_loads=4) as s:
        li.run(s, ctx(terms=["a", "b"], max_pages=1))
    assert b in page.visited


def test_card_without_company_is_skipped_without_detail_load():
    u0 = li.search_url("ml", 48)
    bad = card("5"); bad["primaryDescription"] = None
    page = FakePage({u0: [(CARD_URL, {"included": [bad]})], li.job_url("5"): [(DET_URL, {"included": [det("5")]})]})
    with make_session(page) as s:
        assert li.run(s, ctx(max_pages=1)) == []
    assert li.job_url("5") not in page.visited


def test_incremental_uses_ctx_hours():
    u = li.search_url("ml", 168)
    page = page_for({u: ["1"]}, details=["1"])
    with make_session(page) as s:
        out = li.run(s, ctx(hours=168, max_pages=1))
    assert len(out) == 1 and page.visited == [u]
