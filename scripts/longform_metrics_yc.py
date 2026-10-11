"""Score the long-form answer pipelines on Work at a Startup (YC) applications.

A YC application is ONE free-text message to the founders ("Reach out to <founder> at <company>": a single textarea, 50+
characters). So the question is the same for every job; what differs is the job and company. This script never opens or
fills a live form: it uses the job's stored description as the company/role facts.

  PYTHONPATH=src python3 scripts/longform_metrics_yc.py run     # old pipeline vs new (per-ask), 10 jobs, local judge
  PYTHONPATH=src python3 scripts/longform_metrics_yc.py report  # data/reports/longform_metrics_yc_<date>.md

Rows go to `answer_metrics` with qa_id = -job_id, variants old_longform / asks."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import longform_metrics as L                                          # noqa: E402
from career_agent.longform import metrics as M                        # noqa: E402
from career_agent.longform.kb import KnowledgeBase                    # noqa: E402
from career_agent.longform.pipeline import answer_longform            # noqa: E402
from career_agent.longform.segments import answer_segmented           # noqa: E402
from career_agent.memory.qbank import default_embed                   # noqa: E402

JOBS = (29169, 29158, 29126, 29161, 29133, 29157, 30122, 29132, 29172, 30125)
Q = ("Reach out to the founders at {company}. In a short message, tell them a little about yourself, what you have built "
     "that is relevant to the {title} role, and why you want to work on {company}.")


def question(job: dict) -> str:
    return Q.format(company=job["company"], title=job["title"])


def run():
    c = L.conn()
    judge, name = L.local_judge(), "local"
    kb = KnowledgeBase.load(sqlite3.connect(L.DB), L.ING, {}, embed=default_embed)
    from job_dashboard.db import get_job
    for n, jid in enumerate(JOBS, 1):
        job = dict(get_job(c, jid))
        q = question(job)
        row = {"id": -jid, "job_id": jid, "label": q}
        done = {r[0] for r in c.execute("SELECT variant FROM answer_metrics WHERE qa_id=? AND judge=?", (-jid, name))}
        if {"old_longform", "asks"} <= done:
            continue
        t0 = time.time()
        items = M.required_items(q, judge)
        if "old_longform" not in done:
            out = answer_longform(q, job=job, kb=kb, llm=L.judge_writer(), research=None)
            ch = out.get("chunks") or []
            L.save(c, row, "old_longform", name, M.score_retrieval(q, ch, judge, items=items),
                   M.score_answer(q, out["answer"] or "", ch, judge, items=items) if out["answer"] else None, ch, out["answer"])
        if "asks" not in done:
            out = answer_segmented(q, job=job, kb=kb, llm=L.judge_writer(), by_asks=True)
            ch = out["chunks"]
            L.save(c, row, "asks", name, M.score_retrieval(q, ch, judge, items=items),
                   M.score_answer(q, out["answer"] or "", ch, judge, items=items) if out["answer"] else None, ch,
                   out["answer"] or "(held: " + "; ".join(out["flags"]) + ")")
        print(f"[{n}/{len(JOBS)}] {job['company'][:22]:22} {time.time() - t0:5.0f}s", flush=True)


def report():
    c = L.conn()
    rows = c.execute("SELECT * FROM answer_metrics WHERE qa_id < 0 AND judge='local' ORDER BY job_id, variant").fetchall()
    by: dict = {}
    for r in rows:
        by.setdefault(r["job_id"], {})[r["variant"]] = r
    mean = L._mean
    lines = [f"# Work at a Startup (YC): long-form metrics ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"{len(by)} YC jobs, one founder message each (the modal has a single 50+ character textarea). Question used: "
             f"*{Q.format(company='<company>', title='<role>')}*", "",
             "| Version | answer relevancy | faithfulness | contextual relevancy | contextual precision | contextual recall | passages |",
             "|---|---|---|---|---|---|---|"]
    for v in ("old_longform", "asks"):
        sel = [by[j][v] for j in by if v in by[j]]
        lines.append(f"| {v} | {mean(r['answer_relevancy'] for r in sel)} | {mean(r['faithfulness'] for r in sel)} | "
                     f"{mean(r['contextual_relevancy'] for r in sel)} | {mean(r['contextual_precision'] for r in sel)} | "
                     f"{mean(r['contextual_recall'] for r in sel)} | {mean(r['n_chunks'] for r in sel)} |")
    lines += ["", "## Per job", "", "| Company | role | answer relevancy old / new | faithfulness old / new | ctx relevancy old / new | held? |", "|---|---|---|---|---|---|"]
    for j, v in by.items():
        co, ti = c.execute("SELECT company, title FROM jobs WHERE id=?", (j,)).fetchone()
        o, n = v.get("old_longform"), v.get("asks")
        held = bool(n and (n["reply"] or "").startswith("(held"))
        f = lambda r, k: (r[k] if r else None)
        lines.append(f"| {co} | {ti[:34]} | {f(o, 'answer_relevancy')} / {f(n, 'answer_relevancy')} | {f(o, 'faithfulness')} / {f(n, 'faithfulness')} | "
                     f"{f(o, 'contextual_relevancy')} / {f(n, 'contextual_relevancy')} | {'yes' if held else ''} |")
    lines += ["", "## Replies", ""]
    for j, v in by.items():
        co, ti = c.execute("SELECT company, title FROM jobs WHERE id=?", (j,)).fetchone()
        o, n = v.get("old_longform"), v.get("asks")
        lines += [f"### {co}: {ti}", "", "**Old pipeline:** " + ((o["reply"] or "(none)") if o else "(none)"), "",
                  "**New (per-ask):** " + ((n["reply"] or "") if n else "(none)"), ""]
    out = ROOT / "data" / "reports" / f"longform_metrics_yc_{datetime.now():%Y%m%d}.md"
    out.write_text("\n".join(lines))
    print(out)


if __name__ == "__main__":
    {"run": run, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
