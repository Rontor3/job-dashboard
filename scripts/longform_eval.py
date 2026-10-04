#!/usr/bin/env python3
"""Live eval with the real local model: need-planning accuracy and project-leak rate over tests/longform/eval_set.json.
Needs Ollama running; stop it afterwards (`pkill -f "Ollama.app"`). Not part of the test suite.

    PYTHONPATH=src python3 scripts/longform_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "longform"))

from career_agent.longform.kb import KnowledgeBase                      # noqa: E402
from career_agent.longform.pipeline import answer_longform               # noqa: E402
from job_dashboard.letter.draft import make_default_llm                 # noqa: E402

FIXTURES = ROOT / "tests" / "longform"


def main() -> int:
    from conftest import FACTS, PROJECT_STORIES, STORIES                  # the same synthetic knowledge the tests use
    data = json.loads((FIXTURES / "fixtures" / "ingredients.json").read_text())
    kb = KnowledgeBase(data["units"], dict(STORIES), dict(PROJECT_STORIES), dict(FACTS), data["skills_pool"])
    cases = json.loads((FIXTURES / "eval_set.json").read_text())
    llm = make_default_llm()
    exact = jaccard = leaks = 0
    for c in cases:
        research = SimpleNamespace(facts=[SimpleNamespace(text=c["company"], source_url="eval")]) if c["company"] else None
        out = answer_longform(c["question"], job={"title": "ML Engineer", "company": "Acme", "description": c["jd"]},
                              kb=kb, llm=llm, research=research)
        gold, got = set(c["gold_needs"]), set(out["needs"])
        exact += gold == got
        jaccard += len(gold & got) / len(gold | got)
        leak = any(f.startswith("project_leak") for f in out["flags"])
        leaks += leak
        print(f"{c['id']:28s} needs={sorted(got)} gold={sorted(gold)} project={out['project_id']} "
              f"flags={out['flags']} {'LEAK' if leak else ''}")
    n = len(cases)
    print(f"\nplan exact match {exact}/{n} | mean Jaccard {jaccard / n:.2f} | drafts with a project leak {leaks}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
