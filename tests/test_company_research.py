"""Tests for the TinyFish company-research adapter (company_research.py)."""

import os

import pytest

from job_dashboard.letter.company_research import Fact, ResearchBundle, company_research


def test_builds_bundle_from_search_and_fetch():
    def fake_search(query, api_key=None):
        return [{"url": "https://acme.com/impact", "title": "Acme impact"}]

    def fake_fetch(urls, api_key=None):
        return [{"url": urls[0], "content": "Acme's fraud platform cut losses 40% ($200M saved)."}]

    b = company_research(
        "Acme", "ML Engineer", "fraud detection role",
        search=fake_search, fetch=fake_fetch, api_key="k",
    )
    assert isinstance(b, ResearchBundle) and not b.empty
    assert any("40%" in f.text or "200M" in f.text for f in b.facts)
    assert all(f.source_url for f in b.facts)


def test_empty_bundle_on_search_error_never_raises():
    def boom(query, api_key=None):
        raise RuntimeError("tinyfish down")

    b = company_research(
        "Acme", "ML", "jd",
        search=boom, fetch=lambda u, api_key=None: [], api_key="k",
    )
    assert b.empty and b.facts == []


def test_empty_bundle_when_no_results():
    b = company_research(
        "Acme", "ML", "jd",
        search=lambda q, api_key=None: [],
        fetch=lambda u, api_key=None: [],
        api_key="k",
    )
    assert b.empty


def test_facts_always_carry_a_nonempty_source_url():
    def fake_search(query, api_key=None):
        return [
            {"url": "https://acme.com/a", "title": "A"},
            {"url": "https://acme.com/b", "title": "B"},
        ]

    def fake_fetch(urls, api_key=None):
        return [
            {"url": u, "content": f"Acme launched a new product and grew revenue 25% at {u}."}
            for u in urls
        ]

    b = company_research(
        "Acme", "Backend Engineer", "distributed systems role",
        search=fake_search, fetch=fake_fetch, api_key="k",
    )
    assert b.facts, "expected at least one impact fact"
    for fact in b.facts:
        assert isinstance(fact, Fact)
        assert isinstance(fact.source_url, str) and fact.source_url


def test_non_string_inputs_never_raise():
    # role is not a string and jd_text has no salient token -> query-building
    # would blow up if it ran outside the never-raises guard.
    b = company_research(
        "Acme", 42, "the and for",
        search=lambda q, api_key=None: [], fetch=lambda u, api_key=None: [],
        api_key="k",
    )
    assert isinstance(b, ResearchBundle) and b.empty and b.facts == []


@pytest.mark.skipif(
    not os.getenv("TINYFISH_API_KEY"), reason="requires TINYFISH_API_KEY for live smoke"
)
def test_live_smoke_real_tinyfish_company_research():
    b = company_research("Anthropic", "AI Engineer", "LLM role")
    assert isinstance(b, ResearchBundle)
    print(f"\n[live smoke] facts={len(b.facts)} queries={b.queries_used}")
    if b.facts:
        print(f"[live smoke] sample fact: {b.facts[0].text!r} <- {b.facts[0].source_url}")
