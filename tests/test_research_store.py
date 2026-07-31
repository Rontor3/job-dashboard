from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.letter.research_store import Resource, resources_from_bundle


def _bundle(facts):
    return ResearchBundle(facts=facts, queries_used=[], empty=not facts)


def test_groups_facts_by_source_url_into_one_resource_each():
    b = _bundle([
        Fact("JPMorgan built a data mesh architecture.", "https://aws.amazon.com/blogs/x"),
        Fact("It cut costs and improved data access.", "https://aws.amazon.com/blogs/x"),
        Fact("Account Confidence Score is an AI/ML fraud score.", "https://www.jpmorgan.com/acs"),
    ])
    res = resources_from_bundle(b)
    assert [r.source_url for r in res] == [
        "https://aws.amazon.com/blogs/x", "https://www.jpmorgan.com/acs"]
    # summary joins the source's top facts; title is the host
    assert "data mesh" in res[0].summary and "improved data access" in res[0].summary
    assert res[0].title == "aws.amazon.com"
    assert res[1].title == "jpmorgan.com"


def test_title_strips_www_and_scheme():
    b = _bundle([Fact("Launched a real-time ranking service.", "https://www.nike.com/tech")])
    assert resources_from_bundle(b)[0].title == "nike.com"


def test_caps_at_six_resources():
    facts = [Fact(f"Fact {i} with $1{i}M revenue.", f"https://ex{i}.com/") for i in range(9)]
    assert len(resources_from_bundle(_bundle(facts))) == 6


def test_empty_bundle_yields_no_resources():
    assert resources_from_bundle(_bundle([])) == []
