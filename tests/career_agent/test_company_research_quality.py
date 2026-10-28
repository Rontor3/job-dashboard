"""Company research keeps only facts about the company and replaces bad stored research (Triosoft's four 'facts' were
Gauss Algorithmic's and Infosys's case studies and a Women's Day post, 2026-10-26)."""
import sqlite3
from career_agent.longform import research as R
from job_dashboard.artifacts_store import _ensure_company_resources_table, upsert_company_resources

JOB = {"company": "Triosoft Technologies", "title": "ML Engineer", "apply_url": "https://www.triosoft.ai/career",
       "job_url": "https://www.naukri.com/job-listings-x-1",
       "description": "Required Skills Python NLP Job Summary We are looking for a Machine Learning Engineer with "
                      "experience in NLP and Conversational AI to build intelligent AI Voice Agents and Chatbot solutions. "
                      "The candidate will be responsible for designing pipelines"}


def test_only_facts_about_the_company_count():
    a = lambda text, url: R.about_company(text, url, "Triosoft Technologies", "https://triosoft.ai")
    assert a("Voice bots for banks", "https://triosoft.ai/products")
    assert not a("Today we celebrate the women at Triosoft", "https://in.linkedin.com/company/triosofttechnologies")
    assert not a("Gauss Algorithmic's top AI case studies", "https://www.gaussalgo.com/case-studies")
    assert a("Triosoft raised a seed round in 2025", "https://news.example.com/triosoft")


def test_the_company_site_skips_boards_and_application_systems():
    assert R.company_site(JOB) == "https://triosoft.ai"
    assert R.company_site({"apply_url": "https://x.wd1.myworkdayjobs.com/j", "job_url": "https://in.indeed.com/v"}) == ""


def test_the_jd_says_what_the_company_builds():
    facts = R.jd_facts(JOB, "Triosoft Technologies")
    assert facts and "AI Voice Agents and Chatbot solutions" in facts[0]["text"]


def test_bad_stored_research_is_replaced(tmp_path):
    conn = sqlite3.connect(tmp_path / "j.db"); conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE jobs (id INTEGER, apply_url TEXT, job_url TEXT)")
    _ensure_company_resources_table(conn)
    upsert_company_resources(conn, "triosoft technologies", [
        {"source_url": "https://www.gaussalgo.com/case-studies", "title": "x", "summary": "Gauss case studies"},
        {"source_url": "https://www.instagram.com/triosoft", "title": "x", "summary": "Women's Day"}])
    good = [{"text": "Triosoft builds voice bots for lenders", "url": "https://triosoft.ai/about"},
            {"text": "Triosoft's chatbot platform serves 40 clients", "url": "https://triosoft.ai/clients"}]
    b = R.research_for(conn, JOB, lookup=lambda company, title: good)
    urls = [f.source_url for f in b.facts]
    assert "https://triosoft.ai/about" in urls and not any("gaussalgo" in u or "instagram" in u for u in urls)
    left = [r[0] for r in conn.execute("SELECT source_url FROM company_resources")]
    assert not any("gaussalgo" in u or "instagram" in u for u in left)
