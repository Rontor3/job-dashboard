import pytest

from job_dashboard.db import init_db, insert_job, top_unranked_jobs
from job_dashboard.match.embedder import compute_embed_scores, cosine
from job_dashboard.models import JobListing


class FakeModel:
    """Deterministic 'embeddings': known texts map to fixed vectors."""
    VECTORS = {
        "PROFILE": [1.0, 0.0],
        "ml job": [0.9, 0.1],     # close to profile
        "chef job": [0.0, 1.0],   # orthogonal to profile
    }

    def encode(self, texts):
        return [self.VECTORS[t] for t in texts]


def _job(n, description):
    return JobListing(source="s", title=f"T{n}", company=f"C{n}",
                      job_url=f"https://x.com/{n}", description=description)


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_compute_embed_scores_scores_all_unscored_and_orders_feed(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, "ml job"))
    insert_job(conn, _job(2, "chef job"))

    scored = compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA")

    assert scored == 2
    top = top_unranked_jobs(conn, limit=10)
    assert top[0]["description"] == "ml job"
    assert top[0]["embed_score"] > top[1]["embed_score"]


def test_compute_embed_scores_skips_already_scored(tmp_path):
    conn = init_db(tmp_path / "t.db")
    insert_job(conn, _job(1, "ml job"))
    compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA")

    assert compute_embed_scores(conn, FakeModel(), "PROFILE", "hashA") == 0


def test_load_default_model_raises_actionable_error_without_dependency(monkeypatch):
    import builtins
    from job_dashboard.match import embedder

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("sentence_transformers"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    with pytest.raises(RuntimeError, match="pip3 install sentence-transformers"):
        embedder.load_default_model()
