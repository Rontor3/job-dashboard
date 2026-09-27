import json, time
import pytest
from job_dashboard.sources.cdp import wellfound as wf
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, FakeRequest, make_session

NOW = time.time()
OP = "tfe/abc"
HDRS = {"x-apollo-signature": "sig", "x-wf-cfp": "cfp", "content-type": "application/json", "cookie": "SECRET"}


def job(i, age_h=1, auto=False, **kw):
    d = {"id": i, "slug": f"role-{i}", "title": "Data Scientist", "description": "<p>Do ML</p>",
         "liveStartAt": NOW - age_h * 3600, "autoPosted": auto, "locationNames": ["Bengaluru"]}
    d.update(kw); return d


def result(jobs, has_next=True, company="Acme"):
    edges = [{"node": {"name": company, "startupId": 1, "slug": "acme", "highlightedJobListings": jobs}}]
    return {"data": {"talent": {"jobSearchResults": {"totalStartupCount": 9, "hasNextPage": has_next,
                                                     "startups": {"edges": edges}}}}}


def feed_page(handler):
    req = FakeRequest("https://wellfound.com/graphql", HDRS, json.dumps(
        {"operationName": "JobSearchResultsX", "variables": {"filterConfigurationInput": {"page": 1}},
         "extensions": {"operationId": OP}}).encode())
    noise = FakeRequest("https://wellfound.com/graphql", HDRS, json.dumps({"operationName": "LastActiveUpdate"}).encode())
    p = FakePage({"https://wellfound.com/jobs": [("https://wellfound.com/graphql", {"data": {}}, noise),
                                                 ("https://wellfound.com/graphql", result([]), req)]})
    p.fetch_handler = handler; p.url = "https://wellfound.com/jobs"
    return p


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=[], max_pages=4, stop_after_known=10**9, hours=48)
    return AdapterContext(**{**base, **kw})


def body_of(fetch):
    return json.loads(fetch[3])


def test_parse_results_and_listing():
    jobs, nxt = wf.parse_results(result([job(1), job(2, auto=True)]))
    assert nxt is True and [j["id"] for j in jobs] == ["1", "2"] and jobs[0]["company"] == "Acme"
    n, e = wf.to_listing(jobs[0]), wf.to_listing(jobs[1])
    assert (n.source, n.external_id, n.job_url) == ("wellfound", "1", "https://wellfound.com/jobs/1-role-1")
    assert (n.apply_kind, e.apply_kind, e.apply_url) == ("native", "external", None)
    assert n.description == "Do ML" and n.location == "Bengaluru" and n.posted_date


def test_replays_page_operation_with_captured_headers_only_and_walks_until_stale():
    pages = {1: result([job(1), job(2)]), 2: result([job(3, age_h=200)]), 3: result([job(4, age_h=300)])}
    def handler(url, m, h, b):
        f = json.loads(b)["variables"]["filterConfigurationInput"]
        return 200, json.dumps(pages.get(f["page"], result([], False)) if not f.get("customJobTitles") else result([], False))
    p = feed_page(handler)
    with make_session(p) as s:
        out = wf.run(s, ctx())
    assert [j.external_id for j in out] == ["1", "2"]
    first = p.fetches[0]
    assert first[1] == "POST" and first[0] == "https://wellfound.com/graphql"
    assert first[2]["x-apollo-signature"] == "sig" and first[2]["x-apollo-operation-name"] == "JobSearchResultsX"
    assert "cookie" not in first[2]                                   # only the allowlisted headers are replayed
    f1 = body_of(first)
    assert f1["extensions"]["operationId"] == OP
    fc = f1["variables"]["filterConfigurationInput"]
    assert (fc["page"], fc["sortBy"], fc["hideOffPlatformJobs"], fc["locationTagIds"]) == (1, "LAST_POSTED", False, [wf.INDIA])


def test_title_queries_run_after_the_unfiltered_walk_and_ids_dedupe():
    def handler(url, m, h, b):
        f = json.loads(b)["variables"]["filterConfigurationInput"]
        if f.get("customJobTitles"):
            return 200, json.dumps(result([job(1), job(50)], False))
        return 200, json.dumps(result([job(1)], False))
    p = feed_page(handler)
    with make_session(p) as s:
        out = wf.run(s, ctx())
    assert sorted(j.external_id for j in out) == ["1", "50"]
    titles = [json.loads(f[3])["variables"]["filterConfigurationInput"].get("customJobTitles") for f in p.fetches]
    assert titles[0] is None and [t for t in titles if t] == [[t] for t in wf.TITLES]


def test_known_jobs_skipped_and_redated():
    def handler(url, m, h, b):
        return 200, json.dumps(result([job(1), job(2)], False))
    p = feed_page(handler); bumped = []
    c = ctx(known=lambda i, u: i == "1"); c.redate = lambda i, u, iso: bumped.append(i) or True
    with make_session(p) as s:
        out = wf.run(s, c)
    assert [j.external_id for j in out] == ["2"] and bumped == ["1"] and c.stats["skipped_known"] == 1


def test_no_feed_request_or_graphql_error_is_blocked():
    p = FakePage({"https://wellfound.com/jobs": []}); p.fetch_handler = lambda *a: (200, "{}")
    with make_session(p) as s:
        with pytest.raises(Blocked):
            wf.run(s, ctx())
    p2 = feed_page(lambda u, m, h, b: (200, json.dumps({"errors": [{"message": "PersistedQueryNotFound"}]})))
    with make_session(p2) as s:
        with pytest.raises(Blocked):
            wf.run(s, ctx())


def test_cap_returns_partial():
    p = feed_page(lambda u, m, h, b: (200, json.dumps(result([job(1)], True))))
    c = ctx()
    with make_session(p, max_loads=2) as s:                # goto + one fetch
        out = wf.run(s, c)
    assert c.stats["capped"] is True and [j.external_id for j in out] == ["1"]


def test_all_title_queries_fit_the_incremental_budget_when_feed_never_dries_up():
    from job_dashboard.sources.cdp.runner import LIMITS_BY_SITE
    pages, cap, _ = LIMITS_BY_SITE["wellfound"]["incremental"]
    n = [0]
    def handler(url, m, h, b):
        n[0] += 1
        return 200, json.dumps(result([job(n[0])], True))
    p = feed_page(handler)
    c = ctx(max_pages=pages)
    with make_session(p, max_loads=cap) as s:
        wf.run(s, c)
    titles = {tuple(json.loads(f[3])["variables"]["filterConfigurationInput"].get("customJobTitles") or []) for f in p.fetches}
    assert not c.stats.get("capped") and {t for t in titles if t} == {(t,) for t in wf.TITLES}


def test_job_without_live_start_counts_as_fresh():
    p = feed_page(lambda u, m, h, b: (200, json.dumps(result([job(1, liveStartAt=None)], False))))
    with make_session(p) as s:
        out = wf.run(s, ctx())
    assert [j.external_id for j in out] == ["1"] and out[0].posted_date is None


def test_off_target_title_is_not_added_but_counted_and_stale_rule_uses_all_jobs():
    p = feed_page(lambda u, m, h, b: (200, json.dumps(result(
        [job(1, title="Chip Conveyor Service Engineer"), job(2)], False))))
    c = ctx(known=lambda i, u: False); seen = []
    c.known = lambda i, u: seen.append(i) or False
    with make_session(p) as s:
        out = wf.run(s, c)
    assert [j.external_id for j in out] == ["2"] and c.stats["off_target"] >= 1 and "1" not in seen
    # off-target but FRESH pages must not trip the stale stop: the target job on page 3 is still reached
    bad = "Python Developer"
    pages = {1: result([job(3, title=bad)]), 2: result([job(4, title=bad)]), 3: result([job(5)], False)}
    def handler(u, m, h, b):
        f = json.loads(b)["variables"]["filterConfigurationInput"]
        return 200, json.dumps(result([], False) if f.get("customJobTitles") else pages.get(f["page"], result([], False)))
    with make_session(feed_page(handler)) as s:
        assert [j.external_id for j in wf.run(s, ctx())] == ["5"]
