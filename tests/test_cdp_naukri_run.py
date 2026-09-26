# tests/test_cdp_naukri_run.py
import pytest
from job_dashboard.sources.cdp import naukri as nk
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, FakeResponse, make_session
from tests.test_cdp_naukri_parse import D

S_URL = "https://www.naukri.com/jobapi/v3/search?pageNo=1"
V_URL = "https://www.naukri.com/jobapi/v4/job/1?microsite=y"


def ctx(known=(), text=(), **kw):
    base = dict(mode="incremental", known=lambda i, u: i in known, terms=["data scientist"], max_pages=2,
                stop_after_known=10, hours=24, known_text=lambda t, c, l: (t, c, l) in text)
    return AdapterContext(**{**base, **kw})


def search_page(term, ids_titles, page=1, hours=24):
    return {nk.search_url(term, hours, page): [(S_URL, {"noOfJobs": 99, "jobDetails": [D(i, title=t) for i, t in ids_titles]})]}


def detail_script(*ids):
    return {nk.job_url(f"/job-listings-x-{i}"): [(V_URL, {"jobDetails": {"jobId": str(i), "description": f"<p>full {i}</p>"}})]
            for i in ids}


def test_new_job_gets_detail_description_and_known_is_skipped():
    script = {**search_page("data scientist", [(1, "A"), (2, "B")]), **search_page("data scientist", [], 2), **detail_script(1)}
    page = FakePage(script)
    c = ctx(known={"2"}); c.redate = lambda *a: True
    with make_session(page) as s:
        out = nk.run(s, c)
    assert [(j.external_id, j.description) for j in out] == [("1", "full 1")]
    assert c.stats["skipped_known"] == 1 and c.stats["redated"] == 1


def test_near_duplicates_collapse_within_run_and_against_db():
    # 3 cards: two identical title/company/location, one already in DB text-wise
    script = {**search_page("data scientist", [(1, "Data Scientist"), (2, "data  scientist"), (3, "Other Role")]),
              **search_page("data scientist", [], 2), **detail_script(1, 3)}
    text = {("Other Role", "Acme", "Bengaluru")}
    c = ctx(text=text)
    with make_session(FakePage(script)) as s:
        out = nk.run(s, c)
    assert [j.external_id for j in out] == ["1"] and c.stats["collapsed"] == 2


def test_details_are_loaded_round_robin_after_all_searches():
    script = {}
    for t in ("a", "b"):
        script.update(search_page(t, [(1 if t == "a" else 2, "T")]))
        script.update(search_page(t, [], 2))
    script.update(detail_script(1, 2))
    page = FakePage(script)
    with make_session(page) as s:
        nk.run(s, ctx(terms=["a", "b"], text=set()))
    urls = [u for u in page.visited if "/job-listings" in u]
    assert page.visited.index(urls[0]) > max(i for i, u in enumerate(page.visited) if "-jobs" in u and "job-listings" not in u)


@pytest.mark.parametrize("status", [403, 406, 429])
def test_blocked_status_on_api_response_aborts(status):
    class P(FakePage):
        def goto(self, url, wait_until=None):
            r = super().goto(url, wait_until)
            for h in list(self.handlers):
                h(FakeResponse("https://www.naukri.com/jobapi/v3/search?x", {}, status=status))
            return r
    with make_session(P()) as s:
        with pytest.raises(Blocked):
            nk.run(s, ctx())


def test_silent_first_load_is_reloaded_once():
    u = nk.search_url("data scientist", 24)
    class P(FakePage):
        n = 0
        def goto(self, url, wait_until=None):
            if url == u:
                P.n += 1
                if P.n == 1:                       # first load fires nothing
                    self.url = url; self.visited.append(url); return FakeResponse(url, None)
            return super().goto(url, wait_until)
    page = P({**search_page("data scientist", [(1, "A")]), **search_page("data scientist", [], 2), **detail_script(1)})
    with make_session(page) as s:
        assert [j.external_id for j in nk.run(s, ctx())] == ["1"]
    assert page.visited.count(u) == 2


def test_cap_returns_partial_and_sets_capped():
    script = {**search_page("data scientist", [(1, "A")]), **detail_script(1)}
    c = ctx()
    with make_session(FakePage(script), max_loads=1) as s:
        assert nk.run(s, c) == [] and c.stats["capped"] is True


def test_no_description_anywhere_is_skipped_not_known():
    script = {**search_page("data scientist", [(1, "A")]), **search_page("data scientist", [], 2)}
    c = ctx()
    with make_session(FakePage(script)) as s:
        assert nk.run(s, c) == []
    assert c.stats["skipped_known"] == 0
