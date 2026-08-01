"""CLI bridge between the /rank Claude Code command and the SQLite database.

`top` prints the highest-embed-score canonical jobs that lack an LLM
evaluation; `record` writes one agent evaluation back. Keeping this as a CLI
means the /rank command shells out instead of embedding SQL in a skill file.
"""
import argparse
import copy
import json
import sys

from job_dashboard.db import init_db, job_detail, record_llm_evaluation, top_unranked_jobs
from job_dashboard.match.eligibility import assess_eligibility, candidate_years_from_profile
from job_dashboard.match.profile_text import compose_profile_text


def apply_eligibility(job, payload, candidate_years):
    """Return a copy of `payload` down-ranked to 'Weak Fit' if `job` fails
    the eligibility bar (experience gap / region). Never mutates `payload`.
    """
    out = copy.deepcopy(payload)
    result = assess_eligibility(job.get("description", ""), candidate_years)
    if result.demote:
        out["verdict"] = "Weak Fit"
        flags = out.get("flags")
        if not isinstance(flags, dict):
            flags = {}
        flags["eligibility"] = result.flags
        out["flags"] = flags
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rank_io")
    sub = parser.add_subparsers(dest="command", required=True)

    top = sub.add_parser("top", help="print top unranked jobs as JSON")
    top.add_argument("--db", required=True)
    top.add_argument("--limit", type=int, default=30)

    record = sub.add_parser("record", help="record one LLM evaluation")
    record.add_argument("--db", required=True)
    record.add_argument("--job-id", type=int, required=True)
    record.add_argument("--file", required=True, help="path to evaluation JSON")

    args = parser.parse_args(argv)
    conn = init_db(args.db)
    try:
        if args.command == "top":
            print(json.dumps(top_unranked_jobs(conn, args.limit), indent=2))
            return 0
        payload = json.loads(open(args.file).read())
        detail = job_detail(conn, args.job_id)
        if detail is not None:
            try:
                candidate_years = candidate_years_from_profile(compose_profile_text().text)
            except Exception:
                candidate_years = 2.0
            payload = apply_eligibility(detail, payload, candidate_years)
        record_llm_evaluation(
            conn, args.job_id,
            llm_score=payload.get("llm_score"),
            verdict=payload.get("verdict"),
            strengths=payload.get("strengths", []),
            gaps=payload.get("gaps", []),
            flags=payload.get("flags", {}),
        )
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
