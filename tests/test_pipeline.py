from job_dashboard import pipeline
from job_dashboard.db import init_db
from job_dashboard.models import JobListing

PROFILE_MD = "# Profile\n- python ml\n"


class FakeModel:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _sources():
    j1 = JobListing(source="a", title="ML Engineer", company="Acme",
                    job_url="https://a.com/1", description="ml work")
    j2 = JobListing(source="b", title="ML Engineer", company="Acme",
                    job_url="https://b.com/2", description="ml work again")
    return [lambda: [j1], lambda: [j2]]


def test_run_pipeline_ingests_dedups_and_scores(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(),
    )

    assert result["ingest"]["new_jobs"] == 2
    assert result["duplicates_marked"] == 1
    assert len(result["suspected_duplicates"]) == 1
    assert result["embed_scored"] == 1  # only the canonical row is scored
    assert result["embed_skipped"] is None


def test_run_pipeline_survives_missing_embedding_dependency(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    def broken_loader():
        raise RuntimeError("sentence-transformers is not installed. pip3 install ...")

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=broken_loader,
    )

    assert result["ingest"]["new_jobs"] == 2       # ingest + dedup still ran
    assert result["duplicates_marked"] == 1
    assert result["embed_scored"] == 0
    assert "sentence-transformers" in result["embed_skipped"]


def test_run_pipeline_survives_missing_profile(tmp_path):
    conn = init_db(tmp_path / "t.db")

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=tmp_path / "missing.md", evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(),
    )

    assert result["embed_scored"] == 0
    assert "/setup" in result["embed_skipped"]


def test_run_pipeline_survives_model_failure_during_scoring(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    class ExplodingModel:
        def encode(self, texts):
            raise RuntimeError("model exploded mid-batch")

    result = pipeline.run_pipeline(
        conn, job_sources=_sources(), company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: ExplodingModel(),
    )

    assert result["ingest"]["new_jobs"] == 2
    assert result["duplicates_marked"] == 1
    assert result["embed_scored"] == 0
    assert "model exploded" in result["embed_skipped"]
