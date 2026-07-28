"""Tests for the best-effort unsupported-company-claim guard (grounding.py)."""

from job_dashboard.letter.company_research import Fact, ResearchBundle
from job_dashboard.letter.grounding import GroundingReport, check_grounding


def test_unsourced_dollar_figure_is_flagged():
    body = "Dear Hiring Manager,\n\nI'm excited that Acme raised $500M last year.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme is a fraud-detection startup.", source_url="https://acme.com")],
        queries_used=["Acme product"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert isinstance(report, GroundingReport)
    assert "$500M" in report.unsupported_company_claims


def test_all_company_claims_sourced_from_research_yields_no_flags():
    fact_text = "Acme's fraud platform cut losses 40% ($200M saved)."
    body = (
        "Dear Hiring Manager,\n\n"
        f"I was drawn to Acme after learning that {fact_text} "
        "I would bring the same rigor to your team.\n\n"
        "Sincerely,\n[Your Name]"
    )
    research = ResearchBundle(
        facts=[Fact(text=fact_text, source_url="https://acme.com/impact")],
        queries_used=["Acme revenue funding milestone"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert report.unsupported_company_claims == []


def test_empty_research_with_a_dollar_figure_is_flagged():
    body = "Dear Hiring Manager,\n\nAcme's $10M platform is impressive.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(facts=[], queries_used=[], empty=True)

    report = check_grounding(body, research, "profile text")

    assert "$10M" in report.unsupported_company_claims


def test_unsourced_funding_term_is_flagged():
    body = "Dear Hiring Manager,\n\nCongratulations on the Series B funding round.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(facts=[], queries_used=[], empty=True)

    report = check_grounding(body, research, "profile text")

    assert any("series b" in c.lower() for c in report.unsupported_company_claims)


def test_ordinary_salutation_boilerplate_is_not_flagged():
    body = "Dear Hiring Manager,\n\nI'm excited about this role.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(facts=[], queries_used=[], empty=True)

    report = check_grounding(body, research, "profile text")

    assert report.unsupported_company_claims == []


def test_unsourced_product_phrase_is_flagged():
    body = "Dear Hiring Manager,\n\nI admire what Acme built with QuantumFlow Analytics.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme is a fraud-detection startup.", source_url="https://acme.com")],
        queries_used=["Acme product"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert "QuantumFlow Analytics" in report.unsupported_company_claims


def test_sourced_product_phrase_is_not_flagged():
    body = "Dear Hiring Manager,\n\nI admire what Acme built with QuantumFlow Analytics.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme launched QuantumFlow Analytics to great acclaim.", source_url="https://acme.com")],
        queries_used=["Acme product"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert "QuantumFlow Analytics" not in report.unsupported_company_claims
