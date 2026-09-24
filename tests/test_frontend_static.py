from fastapi.testclient import TestClient

from job_dashboard.api.app import create_app


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    from job_dashboard.db import init_db
    init_db(db).close()
    return TestClient(create_app(db_path=db))


def test_index_html_is_never_cached_without_revalidation(tmp_path):
    c = _client(tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_immutably(tmp_path):
    c = _client(tmp_path)
    # find whatever hashed JS file the current build produced
    index = c.get("/").text
    import re
    m = re.search(r'src="(/assets/[^"]+\.js)"', index)
    assert m, "expected a hashed JS bundle reference in index.html"
    r = c.get(m.group(1))
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
