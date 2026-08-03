"""Backfill/refresh company industry + type classifications.

    python3 scripts/classify_companies.py [--limit N]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    from job_dashboard.env import load_env_file
    load_env_file()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--db", default="data/jobs.db")
    args = ap.parse_args()
    from job_dashboard.db import init_db
    from job_dashboard.classify.run import classify_unclassified
    conn = init_db(args.db)
    counts = classify_unclassified(conn, limit=args.limit)
    print(f"classified {counts['total']} companies "
          f"(dict={counts['dict']}, llm={counts['llm']}, other={counts['other']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
