from job_dashboard.db import insert_job, suspected_duplicates
from job_dashboard.ingest import run_ingest
from job_dashboard.match.dedup import mark_duplicates
from job_dashboard.match.embedder import compute_embed_scores, load_default_model
from job_dashboard.match.profile_text import (
    EVALUATION_FILE, PROFILE_FILE, compose_profile_text,
)


def run_pipeline(conn, job_sources, company_sources,
                 profile_file=None, evaluation_file=None,
                 model_loader=load_default_model, on_stage=None, browser_fetch=None):
    """ingest -> dedup -> embed-score. Embedding problems of any kind
    (missing dependency, missing profile, model errors) never abort ingest/dedup
    — they surface in embed_skipped."""
    def _stage(name):
        if on_stage is not None:
            on_stage(name)

    _stage("ingesting")
    ingest_result = run_ingest(conn, job_sources, company_sources)
    browser = []
    if browser_fetch is not None:
        _stage("browser sources")
        try:
            listings, site_results = browser_fetch(conn)
            by_site = {r.site: r for r in site_results}
            inserted = {}
            for job in listings:
                if insert_job(conn, job):
                    inserted[job.source] = inserted.get(job.source, 0) + 1
            returned = {j.source for j in listings}
            for r in site_results:
                if r.site in returned:                 # streamed sites already set their own count
                    r.new = inserted.get(r.site, 0)
            browser = [r.as_dict() for r in by_site.values()]
        except Exception as exc:
            browser = [{"site": "browser", "new": 0, "note": f"error: {exc}"}]
    _stage("deduping")
    duplicates_marked = mark_duplicates(conn)

    classified = 0
    try:
        from job_dashboard.classify.run import classify_unclassified
        classified = classify_unclassified(conn).get("total", 0)
    except Exception:
        classified = 0

    embed_scored = 0
    embed_skipped = None
    try:
        _stage("scoring")
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
        "companies_classified": classified,
        "embed_scored": embed_scored,
        "embed_skipped": embed_skipped,
        "browser": browser,
    }
