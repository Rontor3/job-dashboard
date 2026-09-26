import json

from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app
from job_dashboard.linkedin import contacts as C

POST = ("We're hiring an ML Engineer at Fship. Location: Noida. DM or send your resume to "
        "hiring@fship.in, call +91 9643108983, form https://forms.gle/abc123 or "
        "https://lnkd.in/xyz. #Hiring")


def test_extract_contacts():
    c = C.extract_contacts(POST, "https://www.linkedin.com/in/jane/#ab12")
    assert c["emails"] == ["hiring@fship.in"]
    assert c["forms"] == ["https://forms.gle/abc123"]
    assert c["links"] == ["https://lnkd.in/xyz"]          # profile url is noise, dropped
    assert c["phones"] == ["+919643108983"]
    assert c["dm"] is True


def test_apply_channel_priority():
    same = lambda u: u  # noqa: E731
    c = C.extract_contacts(POST)
    assert C.apply_channel(c, same) == ("https://forms.gle/abc123", "form")
    c["forms"] = []
    c["links"] = ["https://www.linkedin.com/jobs/view/1/"]
    assert C.apply_channel(c, same) == ("mailto:hiring@fship.in", "email")  # email beats Easy Apply
    c["emails"] = []
    assert C.apply_channel(c, same)[1] == "external"


def test_text_key_dedupes_reshares():
    assert C.text_key("Hiring! ML eng.") == C.text_key("hiring  ml eng")


class _Fetcher:
    def search_posts(self, keyword, **kw):
        return [{"url": "https://www.linkedin.com/in/jane/#ab12", "poster_name": "Jane Doe",
                 "poster_headline": "TA at Fship", "text": POST, "posted_at": "5h"}]


def test_promote_then_draft_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "resolve_link", lambda u, get=None: u)
    monkeypatch.setattr(C, "extract_role", lambda p, post_fn=None: C._regex_role(p))
    import job_dashboard.api.hiring_routes as R
    monkeypatch.setattr(R, "extract_role", lambda p: C._regex_role(p))
    monkeypatch.setattr(R, "research_role", lambda *a, **k: {
        "company_about": "Logistics.", "role_details": "", "apply_url": "", "website": "", "sources": ["s"]})
    app = create_app(db_path=str(tmp_path / "t.db"), hiring_fetcher=_Fetcher(), embed_model=None)
    c = TestClient(app)
    c.post("/api/hiring/refresh")
    post = c.get("/api/hiring/posts").json()["posts"][0]
    assert post["contacts"]["emails"] == ["hiring@fship.in"]

    job_id = c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"]
    assert c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"] == job_id  # idempotent
    detail = c.get(f"/api/jobs/{job_id}").json()
    assert detail["company"] == "Fship" and detail["description"].startswith(POST)
    assert "Logistics." in detail["description"]

    # no tailored résumé yet → refuse to draft
    assert c.post(f"/api/hiring/posts/{post['id']}/email-draft").status_code == 409


def test_research_role_reads_company_pages():
    from job_dashboard.linkedin.enrich import research_role, enriched_description
    searched, fetched = [], []
    search = lambda q: searched.append(q) or [{"url": "https://fship.in/careers/ml"}]  # noqa: E731
    fetch = lambda urls: fetched.extend(urls) or [{"url": u, "text": "Fship careers. " * 30} for u in urls]  # noqa: E731
    llm = lambda url, body: {"response": json.dumps({  # noqa: E731
        "company_about": "Fship is a logistics platform.", "role_details": "Build ETA models.",
        "apply_url": "https://fship.in/careers/ml", "website": "https://fship.in"})}
    role = {"title": "ML Engineer", "company": "Fship"}
    info = research_role({"text": POST}, role, C.extract_contacts(POST), search=search, fetch=fetch, post_fn=llm)
    assert "https://fship.in" in fetched                    # company domain from recruiter email
    assert any("Fship careers" in q for q in searched)
    assert info["role_details"] == "Build ETA models." and info["sources"]
    desc = enriched_description(POST, info)
    assert desc.startswith(POST) and "Build ETA models." in desc and "logistics platform" in desc


def test_research_role_never_raises():
    from job_dashboard.linkedin.enrich import research_role

    def boom(*a, **k):
        raise RuntimeError("down")
    info = research_role({"text": POST}, {"company": "X"}, C.extract_contacts(POST),
                         search=boom, fetch=boom, post_fn=boom)
    assert info["role_details"] == "" and info["sources"] == []
