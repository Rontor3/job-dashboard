"""Compare retrieval strategies (current, naive, query transformation, HyDE, agentic RAG, and QT+HyDE) on a labelled test set of
the kinds of long-text questions that appear in applications, and time them.

  PYTHONPATH=src python3 scripts/longform_retrieval_bench.py run [--only m1,m2]   # resumable; results in table retrieval_bench
  PYTHONPATH=src python3 scripts/longform_retrieval_bench.py report                # data/reports/retrieval_bench_<date>.md

`run` does the independent methods first; the combined qt_hyde runs only if none of them beats `current` by MARGIN."""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import longform_metrics as L                                       # noqa: E402
from career_agent.longform import retrieval_methods as RM          # noqa: E402
from career_agent.longform.bench import CASES, HELD_OUT, TECH, score_case          # noqa: E402
from career_agent.longform.corpus import Corpus                    # noqa: E402
from career_agent.longform.kb import KnowledgeBase                 # noqa: E402
from career_agent.memory.qbank import default_embed                # noqa: E402

INDEPENDENT = ("current", "naive", "query_transform", "hyde", "agentic")
ALL_METHODS = (*INDEPENDENT, "qt_hyde", "routed")
SETS = {"tuning": CASES, "held": HELD_OUT, "tech": TECH, "all": CASES + HELD_OUT + TECH}
MARGIN = 0.05
FORM_QUESTIONS = 6                      # a typical application with several long-text questions


def conn():
    c = sqlite3.connect(L.DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS retrieval_bench (case_id TEXT, method TEXT, score REAL, calls INTEGER, seconds REAL,
        model_seconds REAL, ids_json TEXT, trace_json TEXT, detail_json TEXT, created_at TEXT, PRIMARY KEY (case_id, method))""")
    c.commit()
    return c


def means(c, methods):
    out = {}
    for m in methods:
        rows = c.execute("SELECT score FROM retrieval_bench WHERE method=?", (m,)).fetchall()
        out[m] = round(sum(r[0] for r in rows) / len(rows), 4) if rows else None
    return out


def run(only=None, which="tuning"):
    c = conn()
    from job_dashboard.apply.store import get_application_profile
    from job_dashboard.db import get_job
    contact = get_application_profile(sqlite3.connect(L.DB)) or {}
    kb = KnowledgeBase.load(sqlite3.connect(L.DB), L.ING, contact, embed=default_embed)
    judge = L.local_judge()
    judge("Reply with the single word: ready")                        # warm the model so the first case is not charged its load time
    corpora = {}

    def do(methods):
        for case in SETS[which]:
            job = dict(get_job(c, case.job_id) or {}) if case.job_id else {}
            if case.id not in corpora:
                corpora[case.id] = Corpus(kb, job)
                corpora[case.id]._vectors()                           # embedding the corpus is one-off set-up, not per-question cost
            for m in methods:
                if c.execute("SELECT 1 FROM retrieval_bench WHERE case_id=? AND method=?", (case.id, m)).fetchone():
                    continue
                llm = RM.Counted(judge)
                res = RM.METHODS[m](case.question, corpora[case.id], llm)
                sc = score_case(case, res.chunks)
                c.execute("INSERT OR REPLACE INTO retrieval_bench VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (case.id, m, sc["score"], res.calls, round(res.seconds, 2), round(llm.seconds, 2), json.dumps(sc["ids"]),
                           json.dumps(res.trace), json.dumps({k: v for k, v in sc.items() if k != "ids"}),
                           datetime.now().isoformat(timespec="seconds")))
                c.commit()
                print(f"{case.id} {m:16} score={sc['score']:.2f} calls={res.calls} {res.seconds:5.1f}s", flush=True)

    do(only or INDEPENDENT)
    if only:
        return
    mn = means(c, INDEPENDENT)
    print("independent means:", mn, flush=True)
    if not any(mn[m] is not None and mn[m] >= mn["current"] + MARGIN for m in INDEPENDENT if m != "current"):
        print("no independent method beat 'current' by", MARGIN, "-> trying QT + HyDE together", flush=True)
        do(("qt_hyde",))


def _section(c, title, cases, methods, L1):
    ids_all = [x.id for x in cases]
    q = ",".join("?" * len(ids_all))
    base = c.execute(f"SELECT AVG(score) FROM retrieval_bench WHERE method='current' AND case_id IN ({q})", ids_all).fetchone()[0]
    L1 += [f"## {title}", "", f"{len(cases)} questions. Time is the method's own latency (local gemma4:26b), set-up excluded.", "",
           "| Method | mean score | vs current | model calls / question | seconds / question (mean) | slowest | added time on a "
           f"{FORM_QUESTIONS}-question form |", "|---|---|---|---|---|---|---|"]
    for m in methods:
        rows = c.execute(f"SELECT score, calls, seconds FROM retrieval_bench WHERE method=? AND case_id IN ({q})", (m, *ids_all)).fetchall()
        if not rows:
            continue
        mean = sum(r["score"] for r in rows) / len(rows)
        secs = [r["seconds"] for r in rows]
        L1.append(f"| {m} | {mean:.3f} | {'' if m == 'current' or base is None else f'{mean - base:+.3f}'} | {statistics.mean(r['calls'] for r in rows):.1f} | "
                  f"{statistics.mean(secs):.1f} | {max(secs):.1f} | {statistics.mean(secs) * FORM_QUESTIONS / 60:.1f} min |")
    types = {}
    for x in cases:
        types.setdefault(x.type, []).append(x.id)
    L1 += ["", f"### {title}: by question type (mean score)", "", "| Type | n | " + " | ".join(methods) + " |", "|---|---|" + "---|" * len(methods)]
    for t, ids in types.items():
        cells = []
        for m in methods:
            r = c.execute(f"SELECT AVG(score) FROM retrieval_bench WHERE method=? AND case_id IN ({','.join('?' * len(ids))})", (m, *ids)).fetchone()[0]
            cells.append("" if r is None else f"{r:.2f}")
        L1.append(f"| {t} | {len(ids)} | " + " | ".join(cells) + " |")
    L1 += ["", f"### {title}: per question", "", "| Case | Type | Question | " + " | ".join(methods) + " |", "|---|---|---|" + "---|" * len(methods)]
    for x in cases:
        cells = []
        for m in methods:
            r = c.execute("SELECT score FROM retrieval_bench WHERE case_id=? AND method=?", (x.id, m)).fetchone()
            cells.append("" if r is None else f"{r[0]:.2f}")
        L1.append(f"| {x.id} | {x.type} | {x.question[:64]} | " + " | ".join(cells) + " |")
    L1.append("")


def report():
    c = conn()
    methods = [m for m in ALL_METHODS if c.execute("SELECT 1 FROM retrieval_bench WHERE method=?", (m,)).fetchone()]
    L1 = [f"# Retrieval strategies compared ({datetime.now():%Y-%m-%d %H:%M})", "",
          "Scores are 0..1 from LABELS (which records a good answer to that type of question must draw on), not from a model, so a method "
          "cannot grade its own work. The tuning set (15) was used while the methods were built; the held-out set (12, new wordings and jobs) was "
          "written before the routed method was run and is the fair test.", ""]
    _section(c, "Held-out set (fair test)", HELD_OUT, methods, L1)
    _section(c, "Technical-interview questions (added after the failure; not blind)", TECH, methods, L1)
    _section(c, "Tuning set", CASES, methods, L1)
    L1 += ["## What each method retrieved (ids), held-out set", ""]
    for case in HELD_OUT:
        L1 += [f"**{case.id} ({case.type})** {case.question[:110]}", ""]
        for m in methods:
            r = c.execute("SELECT ids_json, score, trace_json FROM retrieval_bench WHERE case_id=? AND method=?", (case.id, m)).fetchone()
            if r:
                L1.append(f"- {m} ({r['score']:.2f}) {json.loads(r['trace_json'])[0][:60]}: " + ", ".join(i.replace('passage:tata-', 'p:').replace('passage:', 'p:') for i in json.loads(r["ids_json"])))
        L1.append("")
    out = ROOT / "data" / "reports" / f"retrieval_bench_{datetime.now():%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L1))
    print(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
        which = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else "tuning"
        run(only, which)
    elif cmd == "report":
        report()
