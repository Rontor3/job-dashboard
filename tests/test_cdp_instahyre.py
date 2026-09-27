import json
from datetime import date
from job_dashboard.sources.cdp import instahyre as ih
from job_dashboard.sources.cdp.types import AdapterContext
from tests.cdp_fakes import FakePage, make_session

TODAY = date(2026, 9, 27)


def obj(i, company="Acme", title="Data Scientist"):
    return {"id": i, "title": title, "employer": {"company_name": company}, "locations": "Bangalore",
            "keywords": ["ml"], "public_url": f"https://www.instahyre.com/job-{i}-data-scientist-at-acme-1/"}


def listing(ids, total=99):
    return {"meta": {"total_count": total}, "objects": [obj(i) for i in ids]}


def detail_html(posted, desc="<p>Build models</p>"):
    ld = json.dumps({"@context": "https://schema.org", "@type": "JobPosting", "description": desc})
    return f'<html><script type="application/ld+json">{ld}</script>"datePosted": "{posted}"</html>'


def ctx(**kw):
    base = dict(mode="incremental", known=lambda i, u: False, terms=["data scientist"], max_pages=2,
                stop_after_known=10**9, anchor=0)
    return AdapterContext(**{**base, **kw})


def page(pages, details):
    """pages: {offset: ids}; details: {id: html}. First page arrives by the page's own call."""
    p = FakePage({"https://www.instahyre.com/search-jobs?skills=data%20scientist":
                  [("https://www.instahyre.com/api/v1/job_search?offset=0", listing(pages[0]))]})
    def handler(url, m, h, b):
        if "job_search" in url:
            off = int(url.split("offset=")[1].split("&")[0]); return 200, json.dumps(listing(pages.get(off, [])))
        return 200, details[int(url.split("/job-")[1].split("-")[0])]
    p.fetch_handler = handler; p.url = "https://www.instahyre.com/search-jobs"
    return p


def test_parse_detail_and_listing():
    d = ih.parse_detail(detail_html("2026-09-20"))
    assert d["date"] == date(2026, 9, 20) and d["description"] == "Build models"
    card = ih.parse_list(listing([7]))[0][0]
    j = ih.to_listing(card, d)
    assert (j.source, j.external_id, j.company, j.apply_kind) == ("instahyre", "7", "Acme", "native")
    assert j.posted_date.startswith("2026-09-20") and j.job_url.startswith("https://www.instahyre.com/job-7-")


def test_new_job_fetches_detail_known_and_stale_do_not():
    p = page({0: [30, 20, 19, 18, 10], 20: []}, {30: detail_html("2026-09-25"), 20: detail_html("2026-08-01"),
                                                 19: detail_html("2026-08-01"), 18: detail_html("2026-08-01"), 10: detail_html("2026-09-25")})
    saved, c = [], ctx(known=lambda i, u: False)
    c.save_anchor = saved.append
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["30"]           # 20,19,18 = 3 consecutive stale -> anchor 20 -> 10 skipped unfetched
    assert saved == [20] and c.anchor == 20 and c.stats["skipped_stale"] == 1
    assert not any("/job-10-" in f[0] for f in p.fetches)


def test_known_ids_are_skipped_without_detail_fetch():
    p = page({0: [3, 2], 20: []}, {3: detail_html("2026-09-25")})
    c = ctx(known=lambda i, u: i == "2")
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["3"] and c.stats["skipped_known"] == 1


def test_anchor_from_earlier_runs_skips_low_ids():
    p = page({0: [9, 5], 20: []}, {9: detail_html("2026-09-25")})
    with make_session(p) as s:
        out = ih.run(s, ctx(anchor=5), today=TODAY)
    assert [j.external_id for j in out] == ["9"]


def test_second_page_uses_offset_and_cap_returns_partial():
    p = page({0: [4], 20: [3]}, {4: detail_html("2026-09-25"), 3: detail_html("2026-09-25")})
    with make_session(p) as s:
        assert {j.external_id for j in ih.run(s, ctx(), today=TODAY)} == {"4", "3"}
    assert any("offset=20" in f[0] for f in p.fetches)
    p2 = page({0: [4], 20: [3]}, {4: detail_html("2026-09-25"), 3: detail_html("2026-09-25")})
    c = ctx()
    with make_session(p2, max_loads=2) as s:                # goto + 1 fetch, then the cap
        ih.run(s, c, today=TODAY)
    assert c.stats["capped"] is True


def test_missing_description_is_skipped_not_known():
    p = page({0: [4], 20: []}, {4: detail_html("2026-09-25", desc="")})
    c = ctx()
    with make_session(p) as s:
        assert ih.run(s, c, today=TODAY) == []
    assert c.stats["skipped_known"] == 0


def test_single_stale_outlier_does_not_move_anchor():
    p = page({0: [500, 499, 498, 497], 20: []}, {500: detail_html("2026-09-25"), 499: detail_html("2026-08-01"),
                                                 498: detail_html("2026-09-25"), 497: detail_html("2026-09-25")})
    saved, c = [], ctx()
    c.save_anchor = saved.append
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["500", "498", "497"] and saved == [] and c.anchor == 0


def test_undated_detail_is_not_inserted_or_known():
    p = page({0: [4], 20: []}, {4: "<html>no date</html>"})
    c = ctx()
    with make_session(p) as s:
        assert ih.run(s, c, today=TODAY) == []
    assert c.stats["undated"] == 1 and c.stats["skipped_known"] == 0


def test_empty_first_capture_reloads_once():
    p = page({0: [4], 20: []}, {4: detail_html("2026-09-25")})
    script, calls = p.script, [0]
    p.script = {}
    orig = p.goto
    def goto(url, wait_until=None):
        calls[0] += 1
        if calls[0] == 2:
            p.script = script
        return orig(url, wait_until)
    p.goto = goto
    with make_session(p) as s:
        out = ih.run(s, ctx(), today=TODAY)
    assert calls[0] == 2 and [j.external_id for j in out] == ["4"]


def test_off_target_id_never_triggers_detail_fetch_or_anchor_logic():
    p = page({0: [3, 2], 20: []}, {3: detail_html("2026-09-25"), 2: detail_html("2026-09-25")})
    orig = p.script
    key = next(iter(orig))
    orig[key] = [(u, {"meta": {"total_count": 9}, "objects": [obj(3), obj(2, title="Chip Conveyor Service Engineer")]}) for u, _ in orig[key]]
    p.fetch_handler_orig = p.fetch_handler
    p.fetch_handler = lambda u, m, h, b: (200, json.dumps({"meta": {}, "objects": []})) if "job_search" in u else p.fetch_handler_orig(u, m, h, b)
    c, seen = ctx(), []
    c.known = lambda i, u: seen.append(i) or False
    with make_session(p) as s:
        out = ih.run(s, c, today=TODAY)
    assert [j.external_id for j in out] == ["3"] and c.stats["off_target"] == 1 and seen == ["3"]
    assert not any("/job-2-" in f[0] for f in p.fetches)
