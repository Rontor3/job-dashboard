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
    import job_dashboard.api.letter_routes as L
    from job_dashboard.letter.company_research import ResearchBundle
    monkeypatch.setattr(L, "company_research", lambda *a, **k: ResearchBundle(facts=[], queries_used=[], empty=True))
    app = create_app(db_path=str(tmp_path / "t.db"), hiring_fetcher=_Fetcher(), embed_model=None)
    c = TestClient(app)
    c.post("/api/hiring/refresh")
    post = c.get("/api/hiring/posts").json()["posts"][0]
    assert post["contacts"]["emails"] == ["hiring@fship.in"]
    assert post["job_id"] is None                          # card shows "Research company"

    job_id = c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"]
    assert c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"] == job_id  # idempotent
    detail = c.get(f"/api/jobs/{job_id}").json()
    assert detail["company"] == "Fship" and detail["description"].startswith(POST)
    assert "Logistics." in detail["description"]
    from job_dashboard.db import init_db
    from job_dashboard.artifacts_store import cover_letters_for_job
    letters = cover_letters_for_job(init_db(str(tmp_path / "t.db")), job_id)
    assert len(letters) == 1 and letters[0]["body"]              # drafted once, reused
    listed = c.get("/api/hiring/posts").json()["posts"][0]
    assert listed["job_id"] == job_id and listed["apply_kind"]   # card flips to "Draft email"



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


def test_degree_abbrev_is_not_a_link_and_lnkd_skips_static_assets():
    assert C.extract_contacts("Eligibility: http://B.Tech or M.Sc")["links"] == []
    assert C.extract_contacts("Apply https://t.mercor.com/WUK1D")["links"] == ["https://t.mercor.com/WUK1D"]

    class R:
        url = "https://lnkd.in/abc"
        text = ('<link href="https://static.licdn.com/aero/x.css">'
                '<a href="https://docs.google.com/forms/d/e/XYZ/viewform">go</a>')
    assert C.resolve_link("https://lnkd.in/abc", get=lambda u: R()) == \
        "https://docs.google.com/forms/d/e/XYZ/viewform"


def test_enrich_skips_offtopic_search_hits_and_survives_a_dead_site():
    from job_dashboard.linkedin.enrich import research_role
    search = lambda q: [{"url": "https://roberthalf.com/jobs/ml", "title": "ML jobs"},  # noqa: E731
                        {"url": "https://fship.in/about", "title": "About Fship"}]
    fetched = []

    def fetch(urls):
        fetched.extend(urls)
        if urls[0] == "https://fship.in":
            raise RuntimeError("dead site")
        return [{"url": urls[0], "text": "x" * 300}]
    llm = lambda url, body: {"response": json.dumps({"company_about": "ok"})}  # noqa: E731
    info = research_role({"text": POST}, {"title": "ML", "company": "Fship"}, C.extract_contacts(POST),
                         search=search, fetch=fetch, post_fn=llm)
    assert not any("roberthalf" in u for u in fetched)
    assert info["company_about"] == "ok" and "https://fship.in/about" in info["sources"]


def test_short_link_to_form_is_form_and_entities_unescaped():
    c = C.extract_contacts("Apply https://lnkd.in/abc")
    assert C.apply_channel(c, lambda u: "https://forms.gle/q") == ("https://forms.gle/q", "form")

    class R:
        url = "https://lnkd.in/abc"
        text = '<a href="https://jobs.x.ai/p?a=1&amp;b=2">go</a>'
    assert C.resolve_link("https://lnkd.in/abc", get=lambda u: R()) == "https://jobs.x.ai/p?a=1&b=2"


def test_judge_caps_location_and_drops_poster_as_company():
    llm = lambda url, body: {"response": json.dumps({  # noqa: E731
        "title": "Senior ML Engineer", "company": "Jane Doe (Recruiter)", "location_open": False,
        "fit": 80, "reason": "Skills match but on-site in Atlanta, no sponsorship"})}
    j = C.judge_post({"text": "Hiring ML Engineer", "poster_name": "Jane Doe"}, "resume", post_fn=llm)
    assert j["fit"] == 30 and j["company"] == "" and j["title"] == "Senior ML Engineer"


def test_judge_gate_skips_llm_for_non_ml_posts():
    from job_dashboard.linkedin.hiring_digest import HiringPost, judge
    calls = []
    chef = HiringPost(url="u", poster_name="n", poster_headline="", text="We are hiring a chef in Pune",
                      posted_at=None, keyword="k")
    assert judge(chef, lambda p: calls.append(1) or {"title": "Chef", "fit": 90}) == (False, None, "")
    assert calls == []


def test_email_draft_opens_gmail(tmp_path, monkeypatch):
    import job_dashboard.api.hiring_routes as R
    from urllib.parse import parse_qs, urlparse
    monkeypatch.setattr(R.gmail_draft, "authorized", lambda: False)
    c = TestClient(create_app(db_path=str(tmp_path / "t.db"), hiring_fetcher=_Fetcher(), embed_model=None))
    c.post("/api/hiring/refresh")
    pid = c.get("/api/hiring/posts").json()["posts"][0]["id"]
    d = c.post(f"/api/hiring/posts/{pid}/email-draft?to=hiring@fship.in").json()
    q = parse_qs(urlparse(d["gmail_url"]).query)
    assert d["gmail_url"].startswith("https://mail.google.com/mail/?") and d["attached"] is None
    assert q["to"] == ["hiring@fship.in"] and q["view"] == ["cm"] and "Hi Jane" in q["body"][0]
    assert c.post(f"/api/hiring/posts/{pid}/email-draft?to=evil@x.com").status_code == 422

    # authorized → real draft with attachment, opened by message id
    monkeypatch.setattr(R.gmail_draft, "authorized", lambda: True)
    monkeypatch.setenv("CURRENT_RESUME_PDF", str(tmp_path / "cv.pdf"))
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4")
    # a generated CV for the post must NOT be what gets sent
    from job_dashboard.db import init_db
    conn = init_db(str(tmp_path / "t.db"))
    url = conn.execute("SELECT url FROM hiring_posts WHERE id=?", (pid,)).fetchone()[0]
    conn.execute("INSERT INTO jobs (source,title,company,description,job_url,fetched_at) "
                 "VALUES ('linkedin_post','ML','Fship','d',?, 'now')", (url,))
    jid = conn.execute("SELECT id FROM jobs WHERE job_url=?", (url,)).fetchone()[0]
    (tmp_path / "generated.pdf").write_bytes(b"%PDF-1.4")
    conn.execute("INSERT INTO resumes (job_id, pdf_path, created_at) VALUES (?,?, 'now')",
                 (jid, str(tmp_path / "generated.pdf")))
    conn.commit()
    sent = []
    monkeypatch.setattr(R.gmail_draft, "create_draft",
                        lambda msg: sent.append(msg) or {"draft_id": "r1", "message_id": "abc123"})
    d = c.post(f"/api/hiring/posts/{pid}/email-draft").json()
    assert d["gmail_url"].endswith("#drafts?compose=abc123") and d["attached"].endswith("_Resume.pdf") and "cv" not in d["attached"]
    assert sent[0]["To"] == "hiring@fship.in" and sent[0].get_payload()[1].get_filename() == d["attached"]


def test_email_uses_stored_title_company_and_real_first_name(tmp_path, monkeypatch):
    import job_dashboard.api.hiring_routes as R
    from urllib.parse import parse_qs, urlparse
    from job_dashboard.db import init_db, upsert_hiring_post
    monkeypatch.setattr(R.gmail_draft, "authorized", lambda: False)
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    upsert_hiring_post(conn, dict(url="u1", poster_name="K, A S Ammna", poster_headline="HR", keyword="k",
                                  text="URGENTLY HIRING! mail ameena.k@hiil.co.uk", posted_at=None, fit_score=0.8,
                                  fetched_at="2099-01-01T00:00:00+00:00", role_title="AIML Engineer", company="HIIL"))
    c = TestClient(create_app(db_path=db, embed_model=None))
    pid = c.get("/api/hiring/posts?within_hours=1000000").json()["posts"][0]["id"]
    q = parse_qs(urlparse(c.post(f"/api/hiring/posts/{pid}/email-draft").json()["gmail_url"]).query)
    assert q["su"][0] == "Application for the AIML Engineer opening at HIIL"
    assert q["body"][0].startswith("Hi Ammna,") and "the AIML Engineer role at HIIL" in q["body"][0]


def test_requested_subject_from_real_post_formats():
    rs = C.requested_subject
    # "Subject: …" stops before the hashtags
    assert rs("resume at: a.b@gramatix.com Subject: Lead AI Engineer – Remote #Hiring #AI", "Rakshit Singh", "30 days") \
        == "Lead AI Engineer – Remote"
    # placeholders filled from the profile
    assert rs("📌 Subject Line: Senior MLOps Engineer - [Your Name] - [Notice Period] 👉 If you have expertise",
              "Rakshit Singh", "30 days") == "Senior MLOps Engineer - Rakshit Singh - 30 days"
    # 'mention “…”' form
    assert rs("share on my mail. Please mention “Senior Data Scientist – Bangalore” in your application. #Hiring") \
        == "Senior Data Scientist – Bangalore"
    # unknown placeholder or nothing asked → None so the caller falls back
    assert rs("Subject: ML Engineer - [Current CTC] #x", "R", "30 days") is None
    assert rs("Send your CV to hr@x.com", "R", "30 days") is None
    assert rs("Subject: Senior MLOps - [Your Name] - [Notice Period]", "R", "") is None   # no notice period on file


def test_email_subject_uses_requested_else_opening(tmp_path, monkeypatch):
    import job_dashboard.api.hiring_routes as R
    from urllib.parse import parse_qs, urlparse
    from job_dashboard.db import init_db, upsert_hiring_post
    monkeypatch.setattr(R.gmail_draft, "authorized", lambda: False)
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    base = dict(poster_name="Jane Doe", poster_headline="HR", keyword="k", posted_at=None, fit_score=0.8,
                fetched_at="2099-01-01T00:00:00+00:00", role_title="AIML Engineer", company="HIIL")
    upsert_hiring_post(conn, dict(base, url="u1", text="Mail jobs@hiil.co.uk Subject: AIML Engineer – Remote #Hiring"))
    upsert_hiring_post(conn, dict(base, url="u2", text="Mail jobs@hiil.co.uk to apply. #Hiring AI"))
    c = TestClient(create_app(db_path=db, embed_model=None))
    ids = {p["url"]: p["id"] for p in c.get("/api/hiring/posts?within_hours=1000000").json()["posts"]}
    subj = lambda i: parse_qs(urlparse(c.post(f"/api/hiring/posts/{i}/email-draft").json()["gmail_url"]).query)["su"][0]  # noqa: E731
    assert subj(ids["u1"]) == "AIML Engineer – Remote"                        # what the post asked for
    assert subj(ids["u2"]) == "Application for the AIML Engineer opening at HIIL"
