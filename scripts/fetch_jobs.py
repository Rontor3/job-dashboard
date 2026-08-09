"""Daily ingestion: fetch new postings from all sources + embed-score them, then
LLM deep-rank the new (un-verdicted) ones. Idempotent — duplicates are skipped,
already-ranked jobs are left alone — so it's safe to run every day.

    python3 scripts/fetch_jobs.py            # fetch + embed + LLM deep-rank
    python3 scripts/fetch_jobs.py --no-rank  # fetch + embed only

Same operation the dashboard's Refresh button runs, just headless on a schedule.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    from job_dashboard.env import load_env_file
    load_env_file()

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--no-rank", action="store_true",
                    help="skip the LLM deep-rank step (fetch + embed only)")
    args = ap.parse_args()

    from job_dashboard.api.refresh_job import default_pipeline_runner
    print("fetching new postings…", flush=True)
    try:
        result = default_pipeline_runner(args.db, on_stage=lambda s: print(f"  {s}", flush=True))
        print(f"pipeline: {result}", flush=True)
    except Exception as e:  # noqa: BLE001 — a scrape failure shouldn't abort the run
        print(f"fetch error: {e}", flush=True)

    if not args.no_rank:
        try:
            from job_dashboard.db import init_db
            from job_dashboard.match.deep_rank import deep_rank_unranked
            conn = init_db(args.db)
            c = deep_rank_unranked(conn, on_progress=lambda c: None)
            print(f"deep-rank: {c}", flush=True)
        except Exception as e:  # noqa: BLE001 — Ollama down etc. → new jobs keep embed scores
            print(f"deep-rank skipped: {e}", flush=True)


if __name__ == "__main__":
    main()
