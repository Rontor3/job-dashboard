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
    app = create_app(db_path=str(tmp_path / "t.db"), hiring_fetcher=_Fetcher(), embed_model=None)
    c = TestClient(app)
    c.post("/api/hiring/refresh")
    post = c.get("/api/hiring/posts").json()["posts"][0]
    assert post["contacts"]["emails"] == ["hiring@fship.in"]

    job_id = c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"]
    assert c.post(f"/api/hiring/posts/{post['id']}/promote").json()["job_id"] == job_id  # idempotent
    detail = c.get(f"/api/jobs/{job_id}").json()
    assert detail["company"] == "Fship" and detail["description"] == POST

    # no tailored résumé yet → refuse to draft
    assert c.post(f"/api/hiring/posts/{post['id']}/email-draft").status_code == 409
