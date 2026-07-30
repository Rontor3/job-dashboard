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


def test_candidate_metric_in_profile_is_not_flagged_as_company_claim():
    # Two-sided grounding: the candidate's own "30%" (from their profile) is a
    # candidate claim, NOT an unsupported company claim -- must not be flagged.
    body = "Dear Hiring Manager,\n\nMy fraud pipeline improved recall by 30%.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(facts=[], queries_used=[], empty=True)
    profile_text = "Built a health fraud pipeline that improved recall by 30% saving 500 man-hours."

    report = check_grounding(body, research, profile_text)

    assert report.unsupported_company_claims == []


def test_role_title_from_job_text_is_not_flagged():
    # The role title echoed from the JD is not a fabricated company claim.
    body = "Dear Hiring Manager,\n\nI'm applying for the Software Engineer, AI Platform role.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(facts=[], queries_used=[], empty=True)

    report = check_grounding(
        body, research, "profile text",
        job_text="Software Engineer, AI Platform at Notion — build the AI Platform.",
    )

    assert report.unsupported_company_claims == []


def test_fabricated_company_figure_still_flagged_despite_profile_and_job():
    # The two-sided fix must NOT weaken the guard: a $ figure in NEITHER
    # research, profile, nor JD is still surfaced.
    body = "Dear Hiring Manager,\n\nI love that Notion raised $900M.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Notion is a productivity tool.", source_url="https://notion.com")],
        queries_used=["Notion product"],
        empty=False,
    )

    report = check_grounding(
        body, research, "candidate profile with 30% recall",
        job_text="Software Engineer at Notion",
    )

    assert any("$900M" in c for c in report.unsupported_company_claims)


def test_percent_substring_of_larger_figure_is_not_treated_as_supported():
    # Adversarial: a real "140%" fact must NOT bless a fabricated "40%" claim.
    body = "Dear Hiring Manager,\n\nAcme cut fraud losses 40% last year.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme grew revenue 140% year over year.", source_url="https://acme.com")],
        queries_used=["Acme revenue"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert any("40%" in c for c in report.unsupported_company_claims)


def test_genuinely_sourced_percent_is_not_flagged():
    body = "Dear Hiring Manager,\n\nAcme cut fraud losses 40% last year.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme cut fraud losses 40% last year.", source_url="https://acme.com")],
        queries_used=["Acme"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert report.unsupported_company_claims == []


def test_dollar_substring_of_larger_figure_is_not_treated_as_supported():
    # "$5M" fact must NOT bless a fabricated "$50M" claim.
    body = "Dear Hiring Manager,\n\nAcme raised $50M recently.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme raised $5M in seed funding.", source_url="https://acme.com")],
        queries_used=["Acme funding"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert any("$50M" in c for c in report.unsupported_company_claims)


def test_spelled_out_money_and_percent_are_flagged_when_unsourced():
    body = (
        "Dear Hiring Manager,\n\n"
        "Acme raised USD 500 million and grew 40 percent last year.\n\n"
        "Sincerely,\n[Your Name]"
    )
    research = ResearchBundle(facts=[], queries_used=[], empty=True)

    report = check_grounding(body, research, "profile text")

    claims_blob = " ".join(report.unsupported_company_claims).lower()
    assert "500 million" in claims_blob
    assert "40 percent" in claims_blob


def test_sourced_product_phrase_is_not_flagged():
    body = "Dear Hiring Manager,\n\nI admire what Acme built with QuantumFlow Analytics.\n\nSincerely,\n[Your Name]"
    research = ResearchBundle(
        facts=[Fact(text="Acme launched QuantumFlow Analytics to great acclaim.", source_url="https://acme.com")],
        queries_used=["Acme product"],
        empty=False,
    )

    report = check_grounding(body, research, "profile text")

    assert "QuantumFlow Analytics" not in report.unsupported_company_claims
