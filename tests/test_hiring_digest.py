from datetime import datetime, timezone

from job_dashboard.linkedin.hiring_digest import (
    KEYWORDS, HiringPost, to_hiring_post, rank_post, run_digest,
)
from job_dashboard.db import init_db, hiring_posts

# Stamp posts at "now" — hiring_posts(within_hours=24) filters on fetched_at, so
# a hardcoded past date would fall out of the window as wall-clock time advances.
NOW = datetime.now(timezone.utc).isoformat()

DICT_OK = {"url": "https://li/1", "poster_name": "Jane Doe",
           "poster_headline": "EM @ Acme", "text": "Hiring an ML Engineer!",
           "posted_at": "5h"}


class FakeModel:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


class FakeFetcher:
    def __init__(self): self.seen = []
    def search_posts(self, keyword, **kw):
        self.seen.append(keyword)
        return [DICT_OK]


def test_keywords_role_specific():
    assert "hiring machine learning engineer" in KEYWORDS
    assert not any("founding" in k or "startup" in k for k in KEYWORDS)  # generic → off-target posts


def test_to_hiring_post_ok_and_bad():
    p = to_hiring_post(DICT_OK, "hiring ML engineer")
    assert isinstance(p, HiringPost) and p.url == "https://li/1"
    assert to_hiring_post({"text": "no url"}, "k") is None
    assert to_hiring_post({}, "k") is None


def test_rank_post_cosine_range():
    m = FakeModel()
    assert 0.0 <= rank_post("post", m.encode(["profile"])[0], m) <= 1.0


def test_run_digest_skips_flaky_keyword_but_keeps_others(tmp_path):
    # A transient per-keyword browser error must not discard posts already
    # gathered from other keywords.
    conn = init_db(str(tmp_path / "t.db"))

    class FlakyFetcher:
        def search_posts(self, keyword, **kw):
            if keyword == "boom":
                raise RuntimeError("transient WebDriverException")
            return [DICT_OK]

    out = run_digest(conn, FlakyFetcher(), ["hiring ML engineer", "boom"],
                     "profile text", embed_model=FakeModel(),
                     fetched_at=NOW)
    assert len(hiring_posts(conn, within_hours=24)) == 1   # good keyword survived
    assert isinstance(out, list)


def test_run_digest_aborts_on_auth_error(tmp_path):
    from job_dashboard.linkedin.browser_fetch import LinkedInAuthError
    import pytest
    conn = init_db(str(tmp_path / "t.db"))

    class DeadFetcher:
        def search_posts(self, keyword, **kw):
            raise LinkedInAuthError("expired")

    with pytest.raises(LinkedInAuthError):
        run_digest(conn, DeadFetcher(), ["hiring ML engineer"], "p",
                   embed_model=FakeModel(), fetched_at=NOW)


def test_run_digest_dedups_and_stores(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    f = FakeFetcher()
    out = run_digest(conn, f, ["hiring ML engineer", "hiring data scientist"],
                     "profile text", embed_model=FakeModel(),
                     fetched_at=NOW)
    stored = hiring_posts(conn, within_hours=24)
    assert len(stored) == 1                       # same url from 2 keywords deduped
    assert f.seen == ["hiring ML engineer", "hiring data scientist"]
    assert isinstance(out, list)


def test_title_gate_drops_off_target_roles():
    from job_dashboard.linkedin.hiring_digest import is_target_post
    civil = HiringPost(url="u", poster_name="n", poster_headline="HR", text="Hiring Civil Engineer, site work",
                       posted_at=None, keyword="k")
    ml = HiringPost(url="u", poster_name="n", poster_headline="HR", text="We are hiring! ML team, Bengaluru",
                    posted_at=None, keyword="k")
    assert not is_target_post(civil, lambda p: {"title": "Civil Engineer"})
    assert is_target_post(ml, lambda p: {"title": "Senior ML Engineer"})
    # no title from the model → judge by the post's opening
    assert not is_target_post(civil, lambda p: {"title": ""})
    assert is_target_post(HiringPost(url="u", poster_name="n", poster_headline="", posted_at=None, keyword="k",
                                     text="Hiring a Data Scientist in Pune"), None)


def test_run_digest_skips_off_target_posts(tmp_path):
    from job_dashboard.db import init_db, hiring_posts

    class F:
        def search_posts(self, kw, **k):
            return [dict(DICT_OK, url="a", text="Hiring an ML Engineer!"),
                    dict(DICT_OK, url="b", text="Hiring Mechanical GET trainees")]
    conn = init_db(str(tmp_path / "t.db"))
    run_digest(conn, F(), ["k"], "", fetched_at="2099-01-01T00:00:00+00:00",
               role_fn=lambda p: {"title": "ML Engineer" if "ML" in p["text"] else "Mechanical GET"})
    assert [p["url"] for p in hiring_posts(conn, within_hours=10**6)] == ["a"]
