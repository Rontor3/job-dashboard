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
    page = page_for({u0: ["1", "2"], li.search_url("ml", 48, start=25): []}, details=["1", "2"])
    c = ctx(known={"2"})
    with make_session(page) as s:
        out = li.run(s, c)
    assert [j.external_id for j in out] == ["1"] and c.stats["skipped_known"] == 1
    assert page.visited == [u0, li.search_url("ml", 48, start=25)]      # no detail loads


def test_stops_term_after_n_consecutive_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["1", "2", "3", "4"]}, details=[])
    c = ctx(known={"1", "2", "3", "4"}, stop_after_known=3)
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert page.visited == [u0]                                           # page 2 never loaded


def test_card_without_prefetch_gets_detail_load():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=25): []}, details=[],
                    view={"9": [det("9", "from view page")]})
    with make_session(page) as s:
        out = li.run(s, ctx())
    assert out[0].description == "from view page" and li.job_url("9") in page.visited


def test_card_with_no_description_anywhere_is_skipped_not_known():
    u0 = li.search_url("ml", 48)
    page = page_for({u0: ["9"], li.search_url("ml", 48, start=25): []}, details=[])
    c = ctx()
    with make_session(page) as s:
        assert li.run(s, c) == []
    assert c.stats["skipped_known"] == 0


def test_backfill_uses_30_day_window_and_no_early_stop():
    u = li.search_url("ml", 720)
    page = page_for({u: ["1", "2", "3", "4"], li.search_url("ml", 720, start=25): []}, details=["1"])
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
    pages.update({li.search_url(t, 48, start=25): [] for t in ("a", "b")})
    with make_session(page_for(pages, details=["1"])) as s:
        assert len(li.run(s, ctx(terms=["a", "b"]))) == 1
