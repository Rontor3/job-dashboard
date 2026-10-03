"""Question bank maintenance (spec docs/superpowers/specs/2026-09-26-question-bank-design.md).

  PYTHONPATH=src python3 scripts/qbank.py seed        load/refresh src/career_agent/memory/qbank_seed.json (answers untouched)
  PYTHONPATH=src python3 scripts/qbank.py migrate     move usable learned_answers rows into the bank
  PYTHONPATH=src python3 scripts/qbank.py cleanup     seed, then merge overlapping entries / retire rarely-asked ones (idempotent)
  PYTHONPATH=src python3 scripts/qbank.py calibrate   hold-one-out accuracy + suggested FLOOR/HIGH/MARGIN
                                                      (exit 1 below --min-accuracy: retrieval regression check)
"""
import argparse
import json
import sqlite3
import sys

from career_agent.memory import qbank
from career_agent.memory.qbank_admin import calibrate, cleanup, migrate_learned


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "migrate", "cleanup", "calibrate"])
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--min-accuracy", type=float, default=0.85)
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    qbank.ensure(conn)
    embed = qbank.default_embed
    if a.cmd == "seed":
        print(f"seeded {qbank.load_seed(conn, embed)} entries")
    elif a.cmd == "cleanup":
        qbank.load_seed(conn, embed)
        print(json.dumps(cleanup(conn)))
    elif a.cmd == "migrate":
        qbank.seed_if_empty(conn, embed)
        print(json.dumps(migrate_learned(conn, embed), indent=2))
    else:
        r = calibrate(conn, embed)
        print(json.dumps(r, indent=2))
        if r["top1_accuracy"] is not None and r["top1_accuracy"] < a.min_accuracy:
            sys.exit(1)


if __name__ == "__main__":
    main()
