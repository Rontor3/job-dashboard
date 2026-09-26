import time

import pytest
from job_dashboard.sources.cdp import indeed
from job_dashboard.sources.cdp.types import AdapterContext, Blocked
from tests.cdp_fakes import FakePage, make_session
from tests.test_cdp_indeed import C, detail_html, search_html

NOW_MS = int(time.time() * 1000)
FRESH, STALE = NOW_MS - 3600_000, NOW_MS - 400 * 3600_000     # 1h old vs ~17 days old


def ctx(known=(), **kw):
    base = dict(mode="incremental", known=lambda i, u: i in known, terms=["data scientist"], max_pages=2,
                stop_after_known=10, hours=48)
    return AdapterContext(**{**base, **kw})


def search(term, loc, page, cards):
    url = indeed.search_url(term, loc, page)
    return {url: [(url, search_html(cards))]}


def detail(key, **kw):
    url = indeed.job_url(key)
    return {url: [(url, detail_html(**kw))]}


def script(*parts):
    out = {}
    for p in parts:
        out.update(p)
    return out


def quiet(term="data scientist", pages=(0, 1)):
    return [search(term, loc, p, []) for loc in indeed.LOCATIONS for p in pages]


def run(page, c, **kw):
    with make_session(page, **kw) as s:
        return indeed.run(s, c)


def test_new_job_gets_detail_and_known_is_skipped():
    page = FakePage(script(search("data scientist", "India", 0, [C("k1", pubDate=FRESH), C("k2", pubDate=FRESH)]),
                           detail("k1"), *quiet(pages=(1,)), search("data scientist", "Remote", 0, [])))
    c = ctx(known={"k2"})
    out = run(page, c)
    assert [(j.external_id, j.description, j.source) for j in out] == [("k1", "Build models\nPython", "indeed")]
    assert c.stats["skipped_known"] == 1 and c.stats["pages"] == 1
    assert indeed.job_url("k2") not in page.visited


def test_sponsored_cards_are_skipped():
    page = FakePage(script(search("data scientist", "India", 0, [C("ad", pubDate=FRESH, sponsored=True), C("k1", pubDate=FRESH)]),
                           detail("k1"), detail("ad")))
    out = run(page, ctx())
    assert [j.external_id for j in out] == ["k1"] and indeed.job_url("ad") not in page.visited


def test_stale_cards_dropped_and_walk_stops_after_two_stale_pages():
    parts = [search("data scientist", "India", p, [C(f"s{p}", pubDate=STALE)]) for p in range(4)]
    page = FakePage(script(*parts))
    c = ctx(max_pages=4)
    assert run(page, c) == []
    india = [u for u in page.visited if "l=India" in u]
    assert len(india) == 2 and c.stats["pages"] == 2       # pages 0 and 1 stale -> stop; 2, 3 never loaded


def test_fresh_page_resets_the_stale_streak():
    parts = [search("data scientist", "India", 0, [C("s0", pubDate=STALE)]),
             search("data scientist", "India", 1, [C("k1", pubDate=FRESH)]),
             search("data scientist", "India", 2, [C("s2", pubDate=STALE)]), detail("k1")]
    page = FakePage(script(*parts))
    out = run(page, ctx(max_pages=3))
    assert [j.external_id for j in out] == ["k1"]
    assert len([u for u in page.visited if "l=India" in u]) == 3


def test_window_follows_ctx_hours_and_backfill_uses_720():
    cards = [C("k1", pubDate=NOW_MS - 100 * 3600_000)]
    p1 = FakePage(script(search("data scientist", "India", 0, cards), detail("k1")))
    assert run(p1, ctx(hours=48, max_pages=1)) == []
    p2 = FakePage(script(search("data scientist", "India", 0, cards), detail("k1")))
    assert [j.external_id for j in run(p2, ctx(hours=48, max_pages=1, mode="backfill"))] == ["k1"]


def test_off_target_title_never_gets_a_detail_load():
    page = FakePage(script(search("data scientist", "India", 0, [C("k1", title="Social Media Executive", pubDate=FRESH),
                                                                   C("k2", pubDate=FRESH)]), detail("k1"), detail("k2")))
    c = ctx()
    out = run(page, c)
    assert [j.external_id for j in out] == ["k2"]
    assert c.stats["off_target"] == 1 and indeed.job_url("k1") not in page.visited


def test_challenge_on_search_page_raises_blocked():
    url = indeed.search_url("data scientist", "India", 0)
    page = FakePage({url: [(url, "<html><title>Just a moment...</title></html>")]})
    with pytest.raises(Blocked):
        run(page, ctx())


def test_challenge_on_detail_page_raises_blocked():
    u = indeed.job_url("k1")
    page = FakePage(script(search("data scientist", "India", 0, [C("k1", pubDate=FRESH)]),
                           {u: [(u, '<div class="cf-turnstile"></div>')]}))
    with pytest.raises(Blocked):
        run(page, ctx())


def test_plain_200_without_mosaic_or_markers_is_no_results_not_blocked():
    url = indeed.search_url("data scientist", "India", 0)
    c = ctx()
    assert run(FakePage({url: [(url, "<html>0 jobs found</html>")]}), c) == [] and c.stats["pages"] == 0


def test_cap_returns_partial_and_flags_it():
    parts = [search("data scientist", "India", 0, [C(f"k{i}", pubDate=FRESH) for i in (1, 2, 3)]),
             *(detail(f"k{i}") for i in (1, 2, 3))]
    c = ctx(max_pages=1)
    out = run(FakePage(script(*parts)), c, max_loads=4)      # India p0, Remote p0, detail k1, detail k2
    assert [j.external_id for j in out] == ["k1", "k2"] and c.stats["capped"] is True


def test_missing_description_is_skipped_and_not_counted_known():
    seen = set()
    page = FakePage(script(search("data scientist", "India", 0, [C("k1", pubDate=FRESH), C("k2", pubDate=FRESH)]),
                           detail("k1", description=""), detail("k2")))
    c = ctx(max_pages=1, known=seen)
    assert [j.external_id for j in run(page, c)] == ["k2"]
    assert c.stats["skipped_known"] == 0 and c.known("k1", "u") is False


def test_both_locations_searched_and_ids_deduped_across_terms():
    parts = [search(t, loc, 0, [C("k1", pubDate=FRESH)]) for t in ("a", "b") for loc in indeed.LOCATIONS] + [detail("k1")]
    page = FakePage(script(*parts))
    out = run(page, ctx(terms=["a", "b"], max_pages=1))
    assert [j.external_id for j in out] == ["k1"]
    assert sum("l=India" in u for u in page.visited) == 2 and sum("l=Remote" in u for u in page.visited) == 2
    assert page.visited.count(indeed.job_url("k1")) == 1


def test_details_load_after_all_searches_round_robin():
    parts = [search(t, loc, 0, [C(f"{t}{loc[0]}", pubDate=FRESH)]) for t in ("a", "b") for loc in indeed.LOCATIONS]
    parts += [detail(f"{t}{l}") for t in ("a", "b") for l in "IR"]
    page = FakePage(script(*parts))
    out = run(page, ctx(terms=["a", "b"], max_pages=1))
    assert len(out) == 4
    first_detail = min(i for i, u in enumerate(page.visited) if "viewjob" in u)
    assert all("viewjob" in u for u in page.visited[first_detail:]) and first_detail == 4
    assert [u.split("jk=")[1] for u in page.visited[4:]] == ["aI", "aR", "bI", "bR"]
