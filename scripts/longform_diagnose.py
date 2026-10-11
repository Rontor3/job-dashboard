"""For the weakest answers of one iteration: which asks were missed and which claims about the applicant the material does
not support (Haiku lists them). Read this before changing the logic: it is the 'learn from the mistake' step.

  PYTHONPATH=src python3 scripts/longform_diagnose.py --data <checkout>/data --tag it1 --method asks [--below 0.8]"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--below", type=float, default=0.8)
    a = ap.parse_args()
    from career_agent.longform.corpus import Corpus
    from career_agent.longform.kb import KnowledgeBase
    from career_agent.memory.facts import claude_cli_llm
    from career_agent.memory.qbank import default_embed
    from job_dashboard.apply.store import get_application_profile

    data = Path(a.data)
    conn = sqlite3.connect(f"file:{data / 'jobs.db'}?mode=ro", uri=True)
    kb = KnowledgeBase.load(conn, data / "answer_style" / "ingredients.json", get_application_profile(conn) or {}, embed=default_embed)
    corpus = Corpus(kb, {})
    judge = claude_cli_llm("haiku", timeout=180, system="You are a strict fact-checker. Reply with JSON only.")
    for line in (data / "reports" / "longform_iter" / f"{a.tag}.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["method"] != a.method or not r["answer"]:
            continue
        if (r["faithfulness"] or 0) >= a.below and (r["answer_relevancy"] or 0) >= a.below:
            continue
        from career_agent.longform.asks import _links
        chunks = corpus.by_id(*r["chunks"]) + [kb.card(i.split(":", 1)[1]) for i in r["chunks"] if i.startswith("card:")]
        chunks += _links(kb) if "fact:links" in r["chunks"] else []
        chunks = [c for c in chunks if c]
        mat = "\n".join(f"[{c.id}] {c.text}" for c in chunks) or "(none)"
        raw = judge(f"MATERIAL:\n{mat}\n\nANSWER:\n{r['answer']}\n\nList every claim in the ANSWER about the applicant (what they did, "
                    "built, used, measured, achieved) that the MATERIAL does NOT state. Reply with ONLY JSON: "
                    '{"unsupported": [{"claim": "...", "why": "absent | contradicts | inflated"}]}')
        i = raw.find("{")
        try:
            bad = json.JSONDecoder().raw_decode(raw[i:])[0].get("unsupported", []) if i >= 0 else []
        except ValueError:
            bad = [{"claim": "(unreadable judge reply)", "why": ""}]
        missed = [it for it, ok in zip(r["items"], r["addressed"] or []) if not ok]
        print(f"=== qa {r['qa_id']} AR={r['answer_relevancy']} F={r['faithfulness']}\nQ: {r['question'][:200]}")
        print(f"MISSED ASKS: {missed}")
        for b in bad:
            print(f"  UNSUPPORTED ({b.get('why')}): {b.get('claim')}")
        print(f"ANSWER: {r['answer'][:700]}\n")


if __name__ == "__main__":
    main()
