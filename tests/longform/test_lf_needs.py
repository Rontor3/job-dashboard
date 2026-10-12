import json

from career_agent.longform.needs import (NEEDS, Plan, build_plan_prompt, heuristic_needs, parse_plan, plan_needs)

IDS = {"p-churn", "p-ocr", "p-graph", "p-portfolio"}


def test_heuristics_map_common_questions():
    h = heuristic_needs
    assert h("Tell me about yourself") == ("intro",)
    assert h("Describe a project you are proud of") == ("one_project",)
    assert h("What interests you about working for this company?") == ("why_company",)
    assert h("Why do you want to join us?") == ("why_company",)
    assert h("What are you looking for in your next role?") == ("looking_for",)
    assert h("Please list down your skillset") == ("skills_list",)
    assert h("List your key projects") == ("projects_overview",)
    assert h("Anything else we should know?") == ("other",)


def test_a_mixed_question_yields_several_needs_in_order_capped_at_three():
    got = heuristic_needs("Share something about you, what you're looking for, or why Acme interests you.")
    assert got == ("intro", "why_company", "looking_for")
    assert len(heuristic_needs("yourself, proud of, why join us, looking for, skillset")) == 3


def test_parse_plan_validates_needs_and_project():
    ok = parse_plan(json.dumps({"needs": ["intro", "bogus", "why_company"], "project_id": "p-ocr", "reason": "r"}), IDS)
    assert ok == Plan(("intro", "why_company"), "p-ocr", "r", "model")
    assert parse_plan(json.dumps({"needs": ["bogus"]}), IDS) is None
    assert parse_plan("not json", IDS) is None
    assert parse_plan(json.dumps({"needs": ["intro"], "project_id": "edu-btech"}), IDS).project_id is None
    assert len(parse_plan(json.dumps({"needs": list(NEEDS)}), IDS).needs) == 3


def test_prompt_lists_needs_and_project_cards_but_no_stories(kb):
    p = build_plan_prompt("Tell me about a project", "We detect fraud rings with graph ML", kb)
    assert "one_project" in p and "p-graph" in p and "Graph Entity Resolution" in p
    assert "high ownership" not in p                                  # stories are not needed to plan


def test_model_plan_is_used_and_project_defaults_by_jd_when_a_need_requires_one(kb):
    llm = lambda p: json.dumps({"needs": ["one_project"], "project_id": None})
    plan = plan_needs("Describe a project you are proud of", "graph neural networks to detect fraud rings", kb, llm)
    assert plan.needs == ("one_project",) and plan.project_id == "p-graph" and plan.source == "model"


def test_falls_back_to_heuristics_when_the_model_fails_or_is_absent(kb):
    def boom(p): raise TimeoutError
    for llm in (None, boom, lambda p: "garbage"):
        plan = plan_needs("Tell me about yourself", "jd", kb, llm)
        assert plan.needs == ("intro",) and plan.source == "heuristic" and plan.project_id is None


def test_a_prior_choice_wins_and_is_marked(kb):
    llm = lambda p: json.dumps({"needs": ["one_project"], "project_id": "p-churn"})
    plan = plan_needs("Describe a project", "jd", kb, llm, prior_project="p-ocr")
    assert plan.project_id == "p-ocr" and plan.source == "prior"
    assert plan_needs("Describe a project", "jd", kb, llm, prior_project="nope").project_id == "p-churn"


def test_deduplicates_repeated_needs_before_capping():
    """Duplicate needs should be deduped before MAX_NEEDS slice, not eaten by it."""
    result = parse_plan(json.dumps({"needs": ["intro", "intro", "intro", "why_company"]}), IDS)
    assert result is not None
    assert result.needs == ("intro", "why_company")


def test_never_raises_on_unhashable_project_id():
    """parse_plan should guard against unhashable project_id values (list/dict) that would raise TypeError."""
    # Test 1: project_id is a list
    result = parse_plan(json.dumps({"needs": ["intro"], "project_id": ["p-ocr"]}), IDS)
    assert result is not None
    assert result.project_id is None
    assert result.needs == ("intro",)

    # Test 2: project_id is a dict
    result = parse_plan(json.dumps({"needs": ["intro"], "project_id": {"id": "p-ocr"}}), IDS)
    assert result is not None
    assert result.project_id is None
    assert result.needs == ("intro",)

    # Test 3: needs contains unhashable items (list, int) that should be filtered
    result = parse_plan(json.dumps({"needs": ["intro", ["x"], 5]}), IDS)
    assert result is not None
    assert result.needs == ("intro",)


def test_the_model_chooses_a_project_only_among_the_top_ranked(kb):
    from career_agent.longform.needs import build_plan_prompt, plan_needs, shortlist
    q = "Tell us about a project using OCR and document vision"
    short = shortlist(q, "", kb)
    assert len(short) == 3 and short[0] == "p-ocr"
    prompt = build_plan_prompt(q, "", kb, short)
    assert all(pid in prompt for pid in short) and sum(f"- {u['id']}:" in prompt for u in kb.projects()) == 3
    outside = next(u["id"] for u in kb.projects() if u["id"] not in short)
    reply = '{"needs": ["one_project"], "project_id": "%s", "reason": "x"}' % outside
    assert plan_needs(q, "", kb, lambda p: reply).project_id == "p-ocr"          # outside the shortlist -> the ranking decides
    ok = '{"needs": ["one_project"], "project_id": "%s", "reason": "x"}' % short[1]
    assert plan_needs(q, "", kb, lambda p: ok).project_id == short[1]            # inside it -> the model's pick stands


def test_a_hypothetical_question_is_planned_as_an_approach():
    from career_agent.longform.needs import heuristic_needs
    for q in ("3. Suppose an AI agent needs to remember a business's information across 6 months. How would you design it?",
              "6. You inherit a production RAG agent with 90% retrieval recall but poor answer quality. What would you investigate first?",
              "How would you turn a prototype into a dependable product?"):
        assert "approach" in heuristic_needs(q)
    assert "approach" not in heuristic_needs("What is the most technically complex system you have built?")


def test_an_unambiguous_hypothetical_is_always_planned_as_an_approach(kb):
    from career_agent.longform.needs import plan_needs
    q = "You inherit a production RAG agent with poor answer quality. What would you investigate first?"
    wrong = '{"needs": ["challenge"], "project_id": null, "reason": "x"}'                 # the model called it a past challenge
    assert plan_needs(q, "", kb, lambda p: wrong).needs[0] == "approach"
