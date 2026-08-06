from fastapi.testclient import TestClient
from job_dashboard.api.app import create_app

DICT_OK = {"url": "https://li/1", "poster_name": "Jane Doe",
           "poster_headline": "EM @ Acme", "text": "Hiring an ML Engineer!",
           "posted_at": "5h"}


class FakeFetcher:
    def search_posts(self, keyword, **kw): return [DICT_OK]


class FakeModel:
    def encode(self, texts): return [[float(len(t)), 1.0] for t in texts]


def _client(tmp_path, fetcher=None):
    db = str(tmp_path / "t.db")
    app = create_app(db_path=db, hiring_fetcher=fetcher or FakeFetcher(),
                     embed_model=FakeModel())
    return TestClient(app)


def test_refresh_then_list(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/hiring/refresh")
    assert r.status_code == 200 and r.json()["ranked"] >= 1
    posts = c.get("/api/hiring/posts").json()["posts"]
    assert posts[0]["poster_name"] == "Jane Doe" and posts[0]["url"] == "https://li/1"


def test_dismiss(tmp_path):
    c = _client(tmp_path)
    c.post("/api/hiring/refresh")
    pid = c.get("/api/hiring/posts").json()["posts"][0]["id"]
    assert c.post(f"/api/hiring/posts/{pid}/dismiss").status_code == 200
    assert c.get("/api/hiring/posts").json()["posts"] == []


def test_refresh_auth_error_returns_503(tmp_path):
    from job_dashboard.linkedin.browser_fetch import LinkedInAuthError

    class Dead:
        def search_posts(self, keyword, **kw):
            raise LinkedInAuthError("LinkedIn session expired — re-paste ...")

    c = _client(tmp_path, fetcher=Dead())
    r = c.post("/api/hiring/refresh")
    assert r.status_code == 503 and "re-paste" in r.json()["detail"].lower()
