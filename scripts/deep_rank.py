"""Deep-rank every un-verdicted job (LLM judge + cheap nuisance filter).

Nuisance titles (designer/professor/sales/…) are auto-marked Poor Fit without an
LLM call; the rest are judged by the local LLM. Idempotent and background-safe.

    python3 scripts/deep_rank.py [--limit N] [--db data/jobs.db]
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
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--db", default="data/jobs.db")
    args = ap.parse_args()

    from job_dashboard.db import init_db
    from job_dashboard.match.deep_rank import deep_rank_unranked
    conn = init_db(args.db)

    def prog(c):
        print(f"  ...{c['total']} ranked (nuisance={c['nuisance']} "
              f"llm={c['llm']} skipped={c['skipped']})", flush=True)

    c = deep_rank_unranked(conn, limit=args.limit, on_progress=prog)
    print(f"done: {c['total']} ranked (nuisance={c['nuisance']}, "
          f"llm={c['llm']}, skipped={c['skipped']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
