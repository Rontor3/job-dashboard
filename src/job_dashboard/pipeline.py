from job_dashboard.db import suspected_duplicates
from job_dashboard.ingest import run_ingest
from job_dashboard.match.dedup import mark_duplicates
from job_dashboard.match.embedder import compute_embed_scores, load_default_model
from job_dashboard.match.profile_text import (
    EVALUATION_FILE, PROFILE_FILE, compose_profile_text,
)


def run_pipeline(conn, job_sources, company_sources,
                 profile_file=None, evaluation_file=None,
                 model_loader=load_default_model):
    """ingest -> dedup -> embed-score. Embedding problems of any kind
    (missing dependency, missing profile, model errors) never abort ingest/dedup
    — they surface in embed_skipped."""
    ingest_result = run_ingest(conn, job_sources, company_sources)
    duplicates_marked = mark_duplicates(conn)

    embed_scored = 0
    embed_skipped = None
    try:
        profile = compose_profile_text(
            profile_file if profile_file is not None else PROFILE_FILE,
            evaluation_file if evaluation_file is not None else EVALUATION_FILE,
        )
        model = model_loader()
        embed_scored = compute_embed_scores(conn, model, profile.text, profile.hash)
    except Exception as exc:
        embed_skipped = str(exc)

    return {
        "ingest": ingest_result,
        "duplicates_marked": duplicates_marked,
        "suspected_duplicates": suspected_duplicates(conn),
        "embed_scored": embed_scored,
        "embed_skipped": embed_skipped,
    }
