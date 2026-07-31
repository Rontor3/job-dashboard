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
