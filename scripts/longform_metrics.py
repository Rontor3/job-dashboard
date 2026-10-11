"""Score long-form answer retrieval and write new replies, for the long-text questions of failed / queued jobs.

  PYTHONPATH=src python3 scripts/longform_metrics.py select            # list the target questions
  PYTHONPATH=src python3 scripts/longform_metrics.py run [--limit N]   # score + new replies (resumable, local judge)
  PYTHONPATH=src python3 scripts/longform_metrics.py crosscheck        # re-judge 5 questions with Claude, compare
  PYTHONPATH=src python3 scripts/longform_metrics.py report            # write data/reports/longform_metrics_<date>.md

Every result goes to table `answer_metrics` in jobs.db. New replies are stored THERE, not in application_qa: the tracker
shows the latest run of a job, and this script must not replace what you see."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_agent.longform import metrics as M                      # noqa: E402
from career_agent.longform.kb import KnowledgeBase                  # noqa: E402
from career_agent.longform.segments import answer_segmented         # noqa: E402
from career_agent.memory.qbank import default_embed                 # noqa: E402

DB = ROOT / "data" / "jobs.db"
ING = ROOT / "data" / "answer_style" / "ingredients.json"
VARIANTS = ("old_project", "passages", "segmented", "asks")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS answer_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, qa_id INTEGER, job_id INTEGER, label TEXT, variant TEXT, judge TEXT,
        needs_retrieval INTEGER, contextual_relevancy REAL, contextual_precision REAL, contextual_recall REAL,
        answer_relevancy REAL, faithfulness REAL, n_chunks INTEGER, reply TEXT, details_json TEXT, created_at TEXT,
        UNIQUE(qa_id, variant, judge))""")
    c.commit()
    return c


def targets(c):
    """Long-text questions (textarea) from the latest run of every failed / queued job."""
    return c.execute("""
        SELECT a.id, a.job_id, a.label, a.answer, a.status, a.context_json, j.company, j.status AS job_status
        FROM application_qa a JOIN jobs j ON j.id = a.job_id
        WHERE j.status IN ('failed', 'saved') AND a.kind = 'textarea'
          AND a.run_key = (SELECT run_key FROM application_qa b WHERE b.job_id = a.job_id ORDER BY id DESC LIMIT 1)
        ORDER BY a.job_id, a.id""").fetchall()


def usable(label: str) -> bool:
    """A real question: has a question mark or at least five words. 'Description', 'Summary' and internal field ids are not."""
    t = (label or "").strip()
    return "?" in t or (len(t.split()) >= 5 and not t.startswith(("cards[", "rec-form")))


def local_judge():
    """The local model at temperature 0, thinking off: a judge should not vary between runs."""
    def judge(prompt: str) -> str:
        body = json.dumps({"model": "gemma4:26b", "prompt": prompt, "stream": False, "think": False,
                           "options": {"temperature": 0}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", body, {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=600).read())["response"]
    return judge


def claude_judge():
    from career_agent.orchestrator.claude_assist import _claude_cli
    return lambda prompt: _claude_cli(prompt, timeout=180)


def old_chunks(kb, row, question):
    """What the earlier pipeline retrieved: the whole source text of the one project it picked."""
    ctx = {}
    try:
        ctx = json.loads(row["context_json"] or "{}")
    except ValueError:
        pass
    pid = ctx.get("project_id") if isinstance(ctx, dict) else None
    pid = pid or (kb.rank_projects(question)[0][0] if kb.rank_projects(question) else None)
    return [c for c in kb.get_project(pid) if c.kind == "source"] if pid else []


def save(c, row, variant, judge_name, retr, ans, chunks, reply):
    details = {k: v for k, v in {**(retr or {}), **(ans or {})}.items() if k not in ("items",)}
    details["items"] = (retr or {}).get("items")
    c.execute("""INSERT OR REPLACE INTO answer_metrics (qa_id, job_id, label, variant, judge, needs_retrieval,
        contextual_relevancy, contextual_precision, contextual_recall, answer_relevancy, faithfulness, n_chunks, reply,
        details_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (row["id"], row["job_id"], row["label"], variant, judge_name,
               int(bool((retr or {}).get("needs_retrieval"))), (retr or {}).get("contextual_relevancy"),
               (retr or {}).get("contextual_precision"), (retr or {}).get("contextual_recall"),
               (ans or {}).get("answer_relevancy"), (ans or {}).get("faithfulness"), len(chunks), reply,
               json.dumps(details, default=str), datetime.now().isoformat(timespec="seconds")))
    c.commit()


def run(limit=None):
    c = conn()
    judge, name = local_judge(), "local"
    kb = KnowledgeBase.load(sqlite3.connect(DB), ING, {}, embed=default_embed)
    from job_dashboard.db import get_job
    rows = [r for r in targets(c) if usable(r["label"])][: limit or None]
    print(f"{len(rows)} questions with real question text", flush=True)
    for n, row in enumerate(rows, 1):
        q = row["label"]
        done = {r[0] for r in c.execute("SELECT variant FROM answer_metrics WHERE qa_id=? AND judge=?", (row["id"], name))}
        if set(VARIANTS) <= done:
            continue
        t0 = time.time()
        job = dict(get_job(c, row["job_id"]) or {})
        items = M.required_items(q, judge)
        if "old_project" not in done:       # the retrieval the earlier pipeline used, and the answer it wrote
            old = old_chunks(kb, row, q)
            retr = M.score_retrieval(q, old, judge, items=items)
            ans = M.score_answer(q, row["answer"] or "", old, judge, items=items) if row["answer"] else None
            save(c, row, "old_project", name, retr, ans, old, row["answer"])
        if "passages" not in done:          # passage-level retrieval, no new answer
            ps = kb.passages(q, 5)
            save(c, row, "passages", name, M.score_retrieval(q, ps, judge, items=items), None, ps, None)
        for variant, by_asks in (("segmented", False), ("asks", True)):
            if variant in done:
                continue                    # the segmented pipeline: coarse split, or one piece per explicit sub-ask
            out = answer_segmented(q, job=job, kb=kb, llm=judge_writer(), limit=None, by_asks=by_asks)
            chunks = out["chunks"]
            retr = M.score_retrieval(q, chunks, judge, items=items)
            ans = M.score_answer(q, out["answer"] or "", chunks, judge, items=items) if out["answer"] else None
            save(c, row, variant, name, retr, ans, chunks, out["answer"] or "(held: " + "; ".join(out["flags"]) + ")")
        print(f"[{n}/{len(rows)}] job {row['job_id']} {row['company'][:18]:18} {time.time() - t0:5.0f}s  {q[:50]!r}", flush=True)


def judge_writer():
    """The writer is the normal local drafter (temperature .4), not the temperature-0 judge."""
    from job_dashboard.letter.draft import make_default_llm
    return make_default_llm()                    # local only: no silent fallback to Claude


def crosscheck(sample=5):
    """Re-judge `sample` questions with Claude and report agreement with the local judge."""
    c = conn()
    cj, lj = claude_judge(), local_judge()
    kb = KnowledgeBase.load(sqlite3.connect(DB), ING, {}, embed=default_embed)
    rows = [r for r in targets(c)][:60]
    picked = [r for r in rows if c.execute("SELECT 1 FROM answer_metrics WHERE qa_id=? AND variant='passages' AND judge='local'", (r["id"],)).fetchone()]
    step = max(1, len(picked) // sample)
    agree = {"relevance": [0, 0], "addressed": [0, 0]}
    lines = []
    for r in picked[::step][:sample]:
        q = r["label"]
        ps = kb.passages(q, 5)
        mine, theirs = M.judge_relevance(q, ps, lj), M.judge_relevance(q, ps, cj)
        if mine is not None and theirs is not None:
            agree["relevance"][0] += sum(a == b for a, b in zip(mine, theirs)); agree["relevance"][1] += len(mine)
        seg = c.execute("SELECT reply FROM answer_metrics WHERE qa_id=? AND variant='segmented' AND judge='local'", (r["id"],)).fetchone()
        items = M.required_items(q, lj)
        if seg and seg[0] and not seg[0].startswith("(held") and items:
            names = [i["item"] for i in items]
            a, b = M.judge_addressed(q, seg[0], names, lj), M.judge_addressed(q, seg[0], names, cj)
            if a is not None and b is not None:
                agree["addressed"][0] += sum(x == y for x, y in zip(a, b)); agree["addressed"][1] += len(a)
        lines.append(f"- {q[:70]!r}: local {mine} | claude {theirs}")
    out = {k: (round(v[0] / v[1], 3) if v[1] else None, v[1]) for k, v in agree.items()}
    Path(ROOT / "data" / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "reports" / "crosscheck.json").write_text(json.dumps({"agreement": out, "detail": lines}, indent=1))
    print(json.dumps(out), "\n" + "\n".join(lines))


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def report():
    c = conn()
    rows = c.execute("SELECT * FROM answer_metrics WHERE judge='local' ORDER BY job_id, qa_id, variant").fetchall()
    if not rows:
        print("nothing scored yet"); return
    by_q: dict = {}
    for r in rows:
        by_q.setdefault(r["qa_id"], {})[r["variant"]] = r
    ret = [q for q, v in by_q.items() if any(x["needs_retrieval"] for x in v.values())]
    lines = [f"# Long-form retrieval metrics ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"{len(by_q)} long-text questions across {len({r['job_id'] for r in rows})} failed or queued jobs; "
             f"{len(ret)} of them need the applicant's own data (the contextual metrics are averaged over those only).", ""]
    lines += ["## Retrieval, questions that need retrieval", "",
              "| Variant | contextual relevancy | contextual precision | contextual recall | passages |", "|---|---|---|---|---|"]
    for v in (*VARIANTS, "asks_v1"):
        sel = [by_q[q][v] for q in ret if v in by_q[q]]
        lines.append(f"| {v} | {_mean(r['contextual_relevancy'] for r in sel)} | {_mean(r['contextual_precision'] for r in sel)} | "
                     f"{_mean(r['contextual_recall'] for r in sel)} | {_mean(r['n_chunks'] for r in sel)} |")
    lines += ["", "## Answers", "", "| Variant | answer relevancy | faithfulness | answers scored |", "|---|---|---|---|"]
    for v in ("old_project", "segmented", "asks_v1", "asks"):
        sel = [by_q[q][v] for q in by_q if v in by_q[q] and by_q[q][v]["answer_relevancy"] is not None]
        lines.append(f"| {v} | {_mean(r['answer_relevancy'] for r in sel)} | {_mean(r['faithfulness'] for r in sel)} | {len(sel)} |")
    lines += ["", "## Per job", "", "| Job | questions | needs retrieval | relevancy old | relevancy new | answer relevancy old | answer relevancy new |", "|---|---|---|---|---|---|---|"]
    jobs: dict = {}
    for q, v in by_q.items():
        jobs.setdefault(next(iter(v.values()))["job_id"], []).append(v)
    for jid, vs in jobs.items():
        co = c.execute("SELECT company FROM jobs WHERE id=?", (jid,)).fetchone()[0]
        nr = [v for v in vs if any(x["needs_retrieval"] for x in v.values())]
        lines.append(f"| {co} ({jid}) | {len(vs)} | {len(nr)} | {_mean(v['old_project']['contextual_relevancy'] for v in nr if 'old_project' in v)} | "
                     f"{_mean(v['asks']['contextual_relevancy'] for v in nr if 'asks' in v)} | "
                     f"{_mean(v['old_project']['answer_relevancy'] for v in vs if 'old_project' in v)} | "
                     f"{_mean(v['asks']['answer_relevancy'] for v in vs if 'asks' in v)} |")
    blind = [r for r in targets(c) if not usable(r["label"])]
    if blind:
        lines += ["", f"## Questions that could not be scored: no question text ({len(blind)})", "",
                  "The form gave the agent only an internal id or a one-word label, so it never knew what these boxes ask:", ""]
        by_job: dict = {}
        for r in blind:
            by_job.setdefault(f"{r['company']} ({r['job_id']})", []).append(r["label"][:48])
        lines += [f"- {k}: {len(v)} box(es), e.g. `{v[0]}`" for k, v in by_job.items()]
    cc = ROOT / "data" / "reports" / "crosscheck.json"
    if cc.exists():
        d = json.loads(cc.read_text())
        lines += ["", "## Claude cross-check (5 questions)", "", f"Agreement with the local judge: {json.dumps(d['agreement'])}", ""]
    lines += ["", "## New replies", ""]
    for q, v in by_q.items():
        s = v.get("asks") or v.get("segmented")
        if not s:
            continue
        o = v.get("old_project")
        lines += [f"### {s['label'][:110]}", f"*job {s['job_id']}; needs retrieval: {bool(s['needs_retrieval'])}; "
                  f"relevancy {s['contextual_relevancy']}, precision {s['contextual_precision']}, recall {s['contextual_recall']}, "
                  f"answer relevancy {s['answer_relevancy']}, faithfulness {s['faithfulness']}*", "",
                  "**Old answer:** " + ((o["reply"] or "(none)") if o else "(none)"), "", "**New reply:** " + (s["reply"] or ""), ""]
    out = ROOT / "data" / "reports" / f"longform_metrics_{datetime.now():%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "select"
    if cmd == "select":
        for r in targets(conn()):
            print("ok " if usable(r["label"]) else "BLIND", r["id"], r["job_id"], r["company"][:16], r["status"], "|", r["label"][:80])
    elif cmd == "run":
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        run(lim)
    elif cmd == "crosscheck":
        crosscheck()
    elif cmd == "report":
        report()
