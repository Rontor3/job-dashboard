from job_dashboard import pipeline
from job_dashboard.db import init_db
from job_dashboard.models import JobListing


class FakeModel:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_run_pipeline_reports_stages_in_order(tmp_path):
    conn = init_db(tmp_path / "t.db")
    profile = tmp_path / "01.md"
    profile.write_text("# P\n- ml\n")
    job = JobListing(source="a", title="T", company="C",
                     job_url="https://x.com/1", description="d")
    stages = []

    pipeline.run_pipeline(
        conn, job_sources=[lambda: [job]], company_sources=[],
        profile_file=profile, evaluation_file=tmp_path / "absent.md",
        model_loader=lambda: FakeModel(), on_stage=stages.append,
    )

    assert stages == ["ingesting", "deduping", "scoring"]
