"""The hiring-post refresh as the ``worker`` runs it: the agent Chrome's LinkedIn search, the embedding model
(loaded on the first run, then kept) and the LLM role judge, against the current résumé."""
from __future__ import annotations

from datetime import datetime, timezone

from job_dashboard.db import init_db


def _constraints(db_path) -> str:
    try:
        conn = init_db(db_path)
        row = conn.execute("SELECT location, work_authorization FROM application_profile").fetchone()
        conn.close()
        return f"Candidate is based in {row[0]}. Work authorization: {row[1]}" if row else ""
    except Exception:  # noqa: BLE001
        return ""


def make_runner(db_path, fetcher=None, model=None, role_fn=None):
    """``run(on_event)`` for HiringRefresh. Nothing heavy happens until the first run."""
    from job_dashboard.linkedin.contacts import judge_post
    from job_dashboard.linkedin.hiring_digest import KEYWORDS, run_digest
    from job_dashboard.match.embedder import LazyModel
    from job_dashboard.match.profile_text import current_resume_text

    if fetcher is None:
        from job_dashboard.linkedin.cdp_fetch import CdpHiringFetcher
        fetcher = CdpHiringFetcher()
    model = model or LazyModel()

    def judge(post):
        # Re-read each call so replacing data/current_resume.pdf needs no restart.
        return judge_post(post, current_resume_text(), _constraints(db_path))

    def run(on_event):
        try:
            profile_text = current_resume_text()
        except Exception:  # noqa: BLE001
            profile_text = ""
        conn = init_db(db_path)
        try:
            run_digest(conn, fetcher, KEYWORDS, profile_text, embed_model=model,
                       fetched_at=datetime.now(timezone.utc).isoformat(),
                       role_fn=role_fn or judge, on_event=on_event)
        finally:
            conn.close()

    return run
