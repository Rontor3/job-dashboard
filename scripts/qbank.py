"""Question bank maintenance (spec docs/superpowers/specs/2026-09-26-question-bank-design.md).

  PYTHONPATH=src python3 scripts/qbank.py seed        load/refresh src/career_agent/memory/qbank_seed.json (answers untouched)
  PYTHONPATH=src python3 scripts/qbank.py cleanup     seed, then merge overlapping entries / retire rarely-asked ones (idempotent)
  PYTHONPATH=src python3 scripts/qbank.py calibrate   hold-one-out accuracy + suggested FLOOR/HIGH/MARGIN
                                                      (exit 1 below --min-accuracy: retrieval regression check)
  PYTHONPATH=src python3 scripts/qbank.py curate      list the pending proposal rows human replies left behind
                                                      (qbank_candidate: nothing feeds an answer from them);
                                                      --approve <id> promotes ONE through the same path a human
                                                      answer enters today (guards print a reason and reject the
                                                      row when it doesn't fit the bank), --reject <id> declines it.
                                                      No bulk import of historical rows.
"""
import argparse
import json
import sqlite3
import sys

from career_agent.memory import qbank
from career_agent.memory.qbank_admin import calibrate, cleanup
from job_dashboard import qa_store


def _curate_list(conn) -> None:
    pending = qa_store.pending_candidates(conn)
    print(f"{len(pending)} pending candidate(s)")
    for c in pending:
        origin = f" — {c['company']}: {c['title']}" if c.get("company") else ""
        print(f"  {c['id']:<5} [{c['qkey']}]{origin}")
        print(f"        {c['question_text']}  =  {c['answer'][:80]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "cleanup", "calibrate", "curate"])
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--min-accuracy", type=float, default=0.85)
    ap.add_argument("--approve", type=int, metavar="ID",
                    help="curate: promote one pending candidate into the bank (guards apply)")
    ap.add_argument("--reject", type=int, metavar="ID", help="curate: mark one pending candidate rejected")
    ap.add_argument("--note", default="", help="curate: optional reason stored with --reject")
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    qbank.ensure(conn)
    qa_store.ensure(conn)              # candidate table + policy_verdict column on any jobs.db
    embed = qbank.default_embed
    if a.cmd == "seed":
        print(f"seeded {qbank.load_seed(conn, embed)} entries")
    elif a.cmd == "cleanup":
        qbank.load_seed(conn, embed)
        print(json.dumps(cleanup(conn)))
    elif a.cmd == "curate":
        if a.approve is not None and a.reject is not None:
            ap.error("choose either --approve or --reject")
        if a.approve is not None:
            r = qa_store.promote_candidate(conn, a.approve, embed)
            print(f"candidate {a.approve}: " +
                  ("promoted into the bank" if r["promoted"] else f"rejected — {r['reason']}"))
        elif a.reject is not None:
            ok = qa_store.set_candidate_status(conn, a.reject, "rejected", a.note)
            print(f"candidate {a.reject}: " + ("rejected" if ok else "not pending (nothing changed)"))
        else:
            _curate_list(conn)
    else:
        r = calibrate(conn, embed)
        print(json.dumps(r, indent=2))
        if r["top1_accuracy"] is not None and r["top1_accuracy"] < a.min_accuracy:
            sys.exit(1)


if __name__ == "__main__":
    main()
