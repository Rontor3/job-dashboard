"""Compare long-form answer logics on the real long questions, judged by Claude Haiku, so a logic can be improved
iteration by iteration against a FIXED yardstick.

  PYTHONPATH=src python3 scripts/longform_iterate.py --data <checkout>/data --methods live,segmented,briefed,technical,routed --set tuning --tag base
  PYTHONPATH=src python3 scripts/longform_iterate.py --data <checkout>/data --methods routed --set heldout --tag it3

Writer: the local model (OLLAMA_MODEL, gemma4:26b), as in a real run. Judge: Claude Haiku via the logged-in CLI (never the
writer judging itself). Score per answer: answer_relevancy (share of the question's explicit asks it addresses — the
priority) and faithfulness (share of its claims about the applicant the material supports). The explicit asks of each
question are judged ONCE and cached (items.json), so every method and every iteration is scored on the same checklist.
Output: <data>/reports/longform_iter/<tag>.jsonl (answers kept, for reading the mistakes) + a summary line per method."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_agent.longform import metrics as M                                    # noqa: E402
from career_agent.longform.kb import KnowledgeBase                                # noqa: E402

TUNING = [1023, 1025, 706, 993, 994, 996, 998, 1010, 1021, 922, 1012]      # application_qa ids
HELDOUT = [1028, 995, 997, 1011, 1013, 748]
JUDGE_SYSTEM = "You are a strict, literal evaluator of job-application answers. Reply with JSON only."


def writer(temperature: float = 0.0):
    """The local model, at temperature 0 by default so one logic always gives one answer: a change in score is the logic,
    not sampling noise (it4 showed +-0.25 swings on untouched questions at the drafter's usual 0.4)."""
    import os
    import urllib.request

    model = os.getenv("OLLAMA_MODEL", "gemma4:26b")

    def llm(prompt: str) -> str:
        body = json.dumps({"model": model, "prompt": prompt, "stream": False, "think": False,
                           "options": {"temperature": temperature}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", body, {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=600).read())["response"]
    return llm


def judge():
    from career_agent.memory.facts import claude_cli_llm
    return claude_cli_llm("haiku", timeout=180, system=JUDGE_SYSTEM)


# ── logics under test: (question, job, kb, corpus, llm) -> {"answer", "chunks", "note"} ──────────────────────────────
def m_live(q, job, kb, corpus, llm):
    from career_agent.longform.pipeline import answer_longform
    out = answer_longform(q, job=job, kb=kb, llm=llm)
    return {"answer": out["answer"], "chunks": out.get("chunks") or [], "note": ",".join(out["flags"])}


def m_segmented(q, job, kb, corpus, llm):
    from career_agent.longform.segments import answer_segmented
    out = answer_segmented(q, job=job, kb=kb, llm=llm, by_asks=True)
    return {"answer": out["answer"], "chunks": out.get("chunks") or [], "note": ",".join(out["flags"])}


def m_briefed(q, job, kb, corpus, llm):
    from career_agent.longform.brief import answer_briefed
    out = answer_briefed(q, job=job, kb=kb, llm=llm)
    return {"answer": out["answer"], "chunks": out.get("chunks") or [], "note": ",".join(out["flags"])}


def m_technical(q, job, kb, corpus, llm):
    from career_agent.longform.technical import answer_technical
    out = answer_technical(q, corpus, llm, llm)
    return {"answer": out["answer"], "chunks": corpus.by_id(*out.get("evidence", [])), "note": out.get("status", "")}


ROUTES = {"method": m_technical, "technical_knowledge": m_technical, "motivation": m_briefed, "role_message": m_briefed}


def m_routed(q, job, kb, corpus, llm):
    """Classify the question once, then use the logic built for that type (default: one piece per explicit ask)."""
    from career_agent.longform.retrieval_methods import classify
    qtype = classify(q, llm)
    out = ROUTES.get(qtype, m_segmented)(q, job, kb, corpus, llm)
    return {**out, "note": f"type={qtype}; {out['note']}"}


def m_asks(q, job, kb, corpus, llm):
    """Ask by ask: material per explicit ask across all projects, one answer taking the asks in order (longform/asks.py)."""
    from career_agent.longform.asks import answer_asks
    out = answer_asks(q, job=job, kb=kb, corpus=corpus, llm=llm)
    return {"answer": out["answer"], "chunks": out["chunks"], "note": ",".join(out["flags"])}


METHODS = {"live": m_live, "segmented": m_segmented, "briefed": m_briefed, "technical": m_technical, "routed": m_routed,
           "asks": m_asks}


def titled(chunks, kb):
    """The judge sees each passage with its project title, as the writer does; otherwise 'on the X project' is judged
    unsupported only because a bare passage never names its project (it9 diagnosis)."""
    from dataclasses import replace

    from career_agent.longform.asks import _title
    return [replace(c, text=f"[Project: {_title(kb, c.project_id)}] {c.text}") if c.project_id else c for c in chunks]


def resolve_chunks(ids, kb, corpus):
    """Chunk objects back from stored ids: corpus records, project cards, the profile-links chunk."""
    from career_agent.longform.asks import _links
    out = corpus.by_id(*ids) + [kb.card(i.split(":", 1)[1]) for i in ids if i.startswith("card:")]
    return [c for c in out + (_links(kb) if "fact:links" in ids else []) if c]


def rescore(data: Path, tags: list[str], methods: set) -> None:
    """Re-judge stored answers with the CURRENT judge (same cached asks), so rounds judged before a judge fix compare fairly."""
    from career_agent.longform.corpus import Corpus
    from career_agent.memory.qbank import default_embed
    from job_dashboard.apply.store import get_application_profile
    conn = sqlite3.connect(f"file:{data / 'jobs.db'}?mode=ro", uri=True)
    kb = KnowledgeBase.load(conn, data / "answer_style" / "ingredients.json", get_application_profile(conn) or {}, embed=default_embed)
    out_dir = data / "reports" / "longform_iter"
    items = json.loads((out_dir / "items.json").read_text())
    jg = judge()
    for tag in tags:
        res: dict = {}
        with (out_dir / f"{tag}.rescored.jsonl").open("w") as fh:
            for line in (out_dir / f"{tag}.jsonl").read_text().splitlines():
                r = json.loads(line)
                if r["method"] not in methods:
                    continue
                chunks = resolve_chunks(r["chunks"], kb, Corpus(kb, {}))
                sc = M.score_answer(r["question"], r["answer"] or "", titled(chunks, kb), jg, items=items[str(r["qa_id"])]) if r["answer"] else {}
                r.update(answer_relevancy=sc.get("answer_relevancy", 0.0), faithfulness=sc.get("faithfulness"))
                fh.write(json.dumps(r) + "\n")
                res.setdefault(r["method"], []).append(r)
                print(f"{tag} {r['method']:9} qa={r['qa_id']} AR={r['answer_relevancy']} F={r['faithfulness']}", flush=True)
        for m, rs in res.items():
            mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
            print(f"RESCORED {tag} {m}: answer_relevancy={mean([x['answer_relevancy'] or 0 for x in rs])} "
                  f"faithfulness={mean([x['faithfulness'] for x in rs if x['faithfulness'] is not None])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--rescore", default="", help="comma-separated tags to re-judge instead of running")
    ap.add_argument("--methods", default="routed")
    ap.add_argument("--set", choices=["tuning", "heldout", "all"], default="tuning")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    if args.rescore:
        rescore(Path(args.data), args.rescore.split(","), set(args.methods.split(",")))
        return
    from career_agent.longform.corpus import Corpus
    from career_agent.memory.qbank import default_embed
    from job_dashboard.apply.store import get_application_profile
    from job_dashboard.db import get_job

    data = Path(args.data)
    conn = sqlite3.connect(f"file:{data / 'jobs.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out_dir = data / "reports" / "longform_iter"
    out_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / "items.json"
    items_cache = json.loads(items_path.read_text()) if items_path.exists() else {}
    kb = KnowledgeBase.load(conn, data / "answer_style" / "ingredients.json", get_application_profile(conn) or {},
                            embed=default_embed)
    ids = {"tuning": TUNING, "heldout": HELDOUT, "all": TUNING + HELDOUT}[args.set]
    rows = {r["id"]: r for r in conn.execute(f"SELECT id, job_id, label FROM application_qa WHERE id IN ({','.join('?' * len(ids))})", ids)}
    llm, jg = writer(), judge()
    summary: dict = {}
    with (out_dir / f"{args.tag}.jsonl").open("a") as fh:
        for qid in ids:
            row = rows[qid]
            q, job = row["label"], dict(get_job(conn, row["job_id"]) or {})
            if str(qid) not in items_cache:                           # the yardstick: judged once, then frozen
                items_cache[str(qid)] = M.explicit_asks(q, jg)
                items_path.write_text(json.dumps(items_cache, indent=1))
            items = items_cache[str(qid)]
            corpus = Corpus(kb, job)
            for name in args.methods.split(","):
                t0 = time.monotonic()
                try:
                    out = METHODS[name](q, job, kb, corpus, llm)
                except Exception as e:
                    out = {"answer": None, "chunks": [], "note": f"crash {type(e).__name__}: {e}"[:200]}
                sc = M.score_answer(q, out["answer"] or "", titled(out["chunks"], kb), jg, items=items) if out["answer"] else {}
                rec = {"tag": args.tag, "method": name, "qa_id": qid, "question": q, "answer": out["answer"],
                       "answer_relevancy": sc.get("answer_relevancy"), "faithfulness": sc.get("faithfulness"),
                       "addressed": sc.get("addressed"), "items": [i["item"] for i in items],
                       "chunks": [c.id for c in out["chunks"]], "note": out["note"], "secs": round(time.monotonic() - t0)}
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                s = summary.setdefault(name, {"ar": [], "f": [], "held": 0})
                if out["answer"]:
                    s["ar"].append(sc.get("answer_relevancy") or 0.0)
                    if sc.get("faithfulness") is not None:
                        s["f"].append(sc["faithfulness"])
                else:
                    s["held"] += 1
                    s["ar"].append(0.0)                               # no answer = nothing asked was answered
                print(f"{name:10} qa={qid} AR={rec['answer_relevancy']} F={rec['faithfulness']} {rec['secs']}s {out['note'][:60]}",
                      flush=True)
    for name, s in summary.items():
        mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        print(f"SUMMARY {args.tag} {name}: answer_relevancy={mean(s['ar'])} faithfulness={mean(s['f'])} held={s['held']}")


if __name__ == "__main__":
    main()
