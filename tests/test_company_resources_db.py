from job_dashboard.db import (
    init_db, company_key, upsert_company_resources, company_resources_for,
    set_selected_resources, selected_resources_for,
)


def _conn(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def _r(u, t="host", s="summary"):
    return {"source_url": u, "title": t, "summary": s}


def test_company_key_normalizes_variants_together():
    assert company_key("JPMorganChase") == company_key("  jpmorganchase  ")
    assert company_key("Acme Inc") == company_key("Acme")


def test_list_returns_rank_order_so_top_2_is_the_best(tmp_path):
    # Regression: the no-pick draft fallback takes company_resources_for(...)[:2];
    # it must return the BEST-ranked (insertion order), not reverse.
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [
        _r("https://a.com/best", s="best"),
        _r("https://a.com/second", s="second"),
        _r("https://a.com/worst", s="worst"),
    ])
    rows = company_resources_for(c, ck)
    assert [r["summary"] for r in rows[:2]] == ["best", "second"]


def test_regather_updates_rank_order(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r("https://a.com/x", s="x"), _r("https://a.com/y", s="y")])
    # a later gather ranks y first
    upsert_company_resources(c, ck, [_r("https://a.com/y", s="y"), _r("https://a.com/x", s="x")])
    assert company_resources_for(c, ck)[0]["source_url"] == "https://a.com/y"


def test_empty_company_key_is_never_a_shared_bucket(tmp_path):
    # Blank company must not pool unrelated jobs into one "" bucket.
    c = _conn(tmp_path)
    assert upsert_company_resources(c, "", [_r("https://a.com/1")]) == 0
    assert company_resources_for(c, "") == []
    set_selected_resources(c, "", ["https://a.com/1"])  # no-op, no raise
    assert selected_resources_for(c, "") == []


def test_upsert_then_list_roundtrip(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r("https://a.com/1"), _r("https://a.com/2")])
    rows = company_resources_for(c, ck)
    assert {r["source_url"] for r in rows} == {"https://a.com/1", "https://a.com/2"}
    assert all(r["selected"] is False for r in rows)


def test_upsert_refreshes_summary_but_preserves_selection(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r("https://a.com/1", s="old")])
    set_selected_resources(c, ck, ["https://a.com/1"])
    upsert_company_resources(c, ck, [_r("https://a.com/1", s="new summary")])
    rows = company_resources_for(c, ck)
    assert len(rows) == 1
    assert rows[0]["summary"] == "new summary"
    assert rows[0]["selected"] is True  # selection survived the refresh


def test_select_caps_at_two_and_clears_prior(tmp_path):
    c = _conn(tmp_path)
    ck = company_key("Acme")
    upsert_company_resources(c, ck, [_r(f"https://a.com/{i}") for i in range(4)])
    set_selected_resources(c, ck, ["https://a.com/0", "https://a.com/1", "https://a.com/2"])
    sel = selected_resources_for(c, ck)
    assert len(sel) == 2  # capped
    set_selected_resources(c, ck, ["https://a.com/3"])
    sel = selected_resources_for(c, ck)
    assert [r["source_url"] for r in sel] == ["https://a.com/3"]  # prior cleared


def test_unknown_company_yields_empty(tmp_path):
    assert company_resources_for(_conn(tmp_path), company_key("Nobody")) == []
