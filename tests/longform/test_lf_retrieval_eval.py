import json
from pathlib import Path

import pytest

from career_agent.longform.kb import SECTIONS
from career_agent.longform.needs import NEEDS, Plan, heuristic_needs
from career_agent.longform.recipes import retrieve

CASES = json.loads((Path(__file__).parent / "eval_set.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_retrieval_for_the_gold_plan_has_full_recall_and_no_overinclusion(kb, case):
    plan = Plan(tuple(case["gold_needs"]), case["gold_project"], "", "gold")
    got = {c.id for c in retrieve(plan, kb, question=case["question"], jd_text=case["jd"], company_text=case["company"])}
    missing = set(case["must_include"]) - got
    extra = set(case["must_exclude"]) & got
    assert not missing, f"missing required chunks: {sorted(missing)}"
    assert not extra, f"over-included chunks: {sorted(extra)}"
    assert len(got) <= case["max_chunks"], f"{len(got)} chunks > {case['max_chunks']}: {sorted(got)}"
    if "max_cards" in case:
        cards = sorted(i for i in got if i.startswith("card:"))
        assert len(cards) <= case["max_cards"], f"{len(cards)} cards > {case['max_cards']}: {cards}"


@pytest.mark.parametrize("case", [c for c in CASES if c["heuristic"]], ids=lambda c: c["id"])
def test_the_regex_planner_finds_the_gold_needs(case):
    assert set(heuristic_needs(case["question"])) == set(case["gold_needs"])


def test_eval_set_is_well_formed(kb):
    assert len(CASES) >= 12 and len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert set(c) >= {"id", "question", "jd", "company", "gold_needs", "gold_project", "must_include", "must_exclude", "max_chunks"}
    pids = {p["id"] for p in kb.projects()}
    known = {"company", "jd", "skills:pool"} | {f"story:{s}" for s in kb.story_slots()}
    for u in kb.units.values():
        known.add(f"source:{u['id']}")
        if u["id"] in pids:
            known |= {f"card:{u['id']}", *(f"project:{u['id']}:{s}" for s in (*SECTIONS, "body"))}
    for c in CASES:
        for i in c["must_include"] + c["must_exclude"]:
            assert i in known or i.startswith("fact:"), f"case {c['id']}: unknown chunk id {i!r}"
        assert c["gold_project"] is None or c["gold_project"] in pids, f"case {c['id']}: unknown gold_project {c['gold_project']!r}"
        for n in c["gold_needs"]:
            assert n in NEEDS, f"case {c['id']}: unknown need {n!r}"
