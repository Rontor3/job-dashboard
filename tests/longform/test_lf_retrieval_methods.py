import json

import numpy as np
import pytest

from career_agent.longform import retrieval_methods as RM
from career_agent.longform.corpus import Corpus
from career_agent.longform.kb import KnowledgeBase

LONG = {
    "p-ocr": "OCR pipeline scoring scanned medical claim documents with vision models and validation. " * 3,
    "p-graph": "Graph community detection over account graphs finds fraud rings using neighbour sampling. " * 3,
    "p-portfolio": "Monte Carlo simulation of ETF weights with a five year backtest of the portfolio. " * 3,
}


@pytest.fixture
def kb():
    units = [{"id": k, "type": "project", "title": k, "tech": [], "tags": [], "source": v} for k, v in LONG.items()]
    units.append({"id": "role", "type": "work_experience", "title": "Data Scientist", "org": "Acme", "from": "08/2023", "to": "present", "source": "x"})
    kb = KnowledgeBase(units, {"story_looking_for": "I want hard applied ML problems."}, {}, {"years_experience": "3"}, ["Python", "SQL"])
    kb.practices = [{"id": "agent_memory", "title": "Memory for agents", "tags": ["memory"], "body": "Split memory into working, episodic and semantic stores."}]
    return kb


def scripted(**by_key):
    def llm(prompt):
        for key, val in by_key.items():
            if key in prompt:
                return val if isinstance(val, str) else val.pop(0)
        return "{}"
    return llm


def test_corpus_holds_every_kind_and_a_practice_question_finds_practice(kb):
    c = Corpus(kb, {"company": "Acme", "description": "We build memory systems for agents. " * 20})
    assert {i.kind for i in c.items} >= {"passage", "fact", "story", "practice", "company"}
    assert c.search("memory for agents working episodic", 2, kinds={"practice"})[0].id == "practice:agent_memory"


def test_overview_returns_the_best_passage_of_every_project(kb):
    assert {c.project_id for c in Corpus(kb).overview()} == set(LONG)


def test_rrf_and_per_unit_cap(kb):
    c = Corpus(kb)
    got = c.search_multi(["fraud rings graph", "monte carlo etf", "ocr scanned documents"], 6, per_unit=1)
    assert len({x.project_id for x in got if x.kind == "passage"}) == len([x for x in got if x.kind == "passage"])


def test_current_baseline_is_a_regex_gate(kb):
    c = Corpus(kb)
    assert RM.current("How would you design memory for an agent?", c, lambda p: 1 / 0).chunks[0].kind == "practice"
    assert all(x.kind == "passage" for x in RM.current("Describe the OCR system you built.", c, lambda p: 1 / 0).chunks)


def test_query_transform_runs_each_query_and_costs_one_call(kb):
    llm = scripted(**{"Rewrite this": json.dumps({"queries": ["fraud rings graph detection", "monte carlo etf backtest"]})})
    r = RM.query_transform("Tell me about your work", Corpus(kb), llm)
    assert r.calls == 1 and {c.project_id for c in r.chunks if c.kind == "passage"} >= {"p-graph", "p-portfolio"}


def test_hyde_searches_with_the_hypothetical_text_not_the_question(kb):
    llm = scripted(**{"plausible answer": "I built a pipeline that scores scanned claim documents with OCR and vision models."})
    r = RM.hyde("What have you shipped?", Corpus(kb), llm)
    assert r.calls == 1 and r.chunks[0].project_id == "p-ocr"


def test_agentic_plans_then_reflects_and_stops_when_done(kb):
    llm = scripted(**{"You plan retrieval": json.dumps({"type": "work_summary", "calls": [{"tool": "overview", "query": ""}, {"tool": "profile", "query": ""}]}),
                      "RETRIEVED SO FAR": json.dumps({"done": True})})
    r = RM.agentic("Summarise your work", Corpus(kb), llm)
    assert r.calls == 2 and {c.project_id for c in r.chunks if c.kind == "passage"} == set(LONG) and any(c.id == "fact:role" for c in r.chunks)


def test_agentic_ignores_an_invented_tool_and_can_ask_for_more(kb):
    llm = scripted(**{"You plan retrieval": json.dumps({"calls": [{"tool": "web_search", "query": "x"}, {"tool": "skills", "query": ""}]}),
                      "RETRIEVED SO FAR": json.dumps({"calls": [{"tool": "practice", "query": "memory for agents"}]})})
    r = RM.agentic("q", Corpus(kb), llm)
    assert [c.id for c in r.chunks] == ["fact:skills", "practice:agent_memory"] and r.calls == 2


def test_counted_tracks_calls_and_time():
    c = RM.Counted(lambda p: "x")
    c("a"); c("b")
    assert c.calls == 2 and c.seconds >= 0


def test_scoring_rewards_breadth_for_a_summary_and_penalises_one_project_everywhere():
    from career_agent.longform.bench import CASES, HF, MD, GR, PE, score_case
    from career_agent.longform.kb import Chunk
    summary = next(c for c in CASES if c.id == "c06")
    one = [Chunk(f"passage:{HF}:{i}", "passage", "x", HF) for i in range(5)]
    many = [Chunk(f"passage:{p}:0", "passage", "x", p) for p in (HF, MD, GR, PE)]
    assert score_case(summary, many)["score"] > score_case(summary, one)["score"] + 0.4
    method = next(c for c in CASES if c.id == "c13")
    assert score_case(method, [Chunk("practice:rag_quality_debug", "practice", "x")])["score"] == 1.0
    assert score_case(method, one)["score"] < 0.1                       # personal records for a how-would-you question
    assert score_case(summary, [])["score"] == 0.0


def test_routed_classifies_once_then_applies_a_fixed_policy(kb):
    c = Corpus(kb)
    summary = RM.routed("Summarize your experience", c, scripted(**{"Classify this": json.dumps({"type": "work_summary"})}))
    assert summary.calls == 1 and {x.project_id for x in summary.chunks if x.kind == "passage"} == set(LONG)
    method = RM.routed("How would you design memory?", c, scripted(**{"Classify this": json.dumps({"type": "method"})}))
    assert [x.kind for x in method.chunks] == ["practice"]
    skills = RM.routed("List your skills", c, scripted(**{"Classify this": json.dumps({"type": "skills"})}))
    assert skills.chunks[0].id == "fact:skills"
    unknown = RM.routed("???", c, scripted(**{"Classify this": "not json"}))
    assert unknown.chunks is not None and unknown.trace[0].startswith("type=unknown")


def test_held_out_cases_are_disjoint_from_the_tuning_cases():
    from career_agent.longform.bench import CASES, HELD_OUT
    assert not ({c.question for c in CASES} & {c.question for c in HELD_OUT}) and not ({c.id for c in CASES} & {c.id for c in HELD_OUT})


def test_who_i_am_puts_the_current_role_before_education(kb):
    kb.units["edu"] = {"id": "edu", "type": "education", "title": "B.Tech", "field": "Ceramics", "org": "IIT", "from": "07/2019", "to": "05/2023", "source": "x"}
    kb._corpus_static = None
    assert [c.id for c in Corpus(kb).facts()] == ["fact:role", "fact:education"]


def test_a_technical_question_gets_no_unrelated_practice_note(kb):
    c = Corpus(kb)
    c.kb.embed = None                                         # no embedder: close() falls back to a high floor on the hybrid rank
    tech = RM.routed("Explain the attention mechanism", c, scripted(**{"Classify this": json.dumps({"type": "technical_knowledge"})}))
    assert not any(x.kind == "practice" for x in tech.chunks)


def test_close_returns_nothing_when_no_record_really_matches():
    import numpy as np
    units = [{"id": "p", "type": "project", "title": "p", "tech": [], "tags": [], "source": "ocr scoring of scanned claim documents " * 5}]
    kb2 = KnowledgeBase(units, embed=lambda texts: np.array([[1.0, 0.0] if "ocr" in t.lower() else [0.0, 1.0] for t in texts], dtype="float32"))
    c = Corpus(kb2)
    assert c.close("explain attention", 1, kinds={"passage"}) == []                 # cosine 0
    assert [x.project_id for x in c.close("ocr documents", 1, kinds={"passage"})] == ["p"]


def test_tech_scoring_penalises_unrelated_notes_and_rewards_a_true_link():
    from career_agent.longform.bench import HF, TECH, score_case
    from career_agent.longform.kb import Chunk
    t1, t2 = TECH[0], TECH[1]                                # t1 has a real project link (HF); t2 has none
    assert score_case(t2, [])["score"] == 1.0                # nothing fetched is right when nothing relates
    assert score_case(t2, [Chunk("practice:agent_memory", "practice", "x")])["score"] == 0.5     # half: the unrelated note is the penalty
    assert score_case(t1, [Chunk(f"passage:{HF}:9", "passage", "x", HF)])["score"] == 1.0
    assert score_case(t1, [])["score"] == 0.5               # no link found: no noise, but the real link was missed


def test_a_technical_answer_makes_no_personal_claim_unless_evidence_was_found():
    from career_agent.longform.kb import Chunk
    from career_agent.longform.technical import write_technical
    seen = []
    llm = lambda p: seen.append(p) or "Boosting fits models in sequence."
    out = write_technical("What is boosting?", [], llm)
    assert out["source"] == "general knowledge" and "NO claims about the applicant" in seen[0] and "In my work" not in seen[0]
    out = write_technical("What is boosting?", [Chunk("passage:p:1", "passage", "I used XGBoost with class weights.", "p")], llm)
    assert out["source"] == "general knowledge + your project" and "In my work, " in seen[1] and "XGBoost" in seen[1]


def test_verify_flags_an_incorrect_claim_and_treats_an_unreadable_reply_as_not_ok():
    from career_agent.longform.technical import verify
    bad = json.dumps({"claims": [{"claim": "bagging is sequential", "verdict": "incorrect", "correction": "bagging is parallel"},
                                 {"claim": "boosting reduces bias", "verdict": "correct"}]})
    r = verify("q", "a", lambda p: bad)
    assert not r["ok"] and r["wrong"][0]["claim"] == "bagging is sequential"
    assert verify("q", "a", lambda p: json.dumps({"claims": [{"claim": "x", "verdict": "correct"}]}))["ok"]
    assert verify("q", "a", lambda p: "I think it looks fine")["ok"] is False


def test_personal_sentence_must_stay_inside_the_passage():
    from career_agent.longform.kb import Chunk
    from career_agent.longform.technical import personal_sentence_ok
    ev = [Chunk("passage:p:1", "passage", "Class imbalance handled with weighting about ten to one, tuned with Optuna.", "p")]
    assert personal_sentence_ok("Boosting works. In my work, I handled class imbalance with weighting.", ev)
    assert not personal_sentence_ok("Boosting works. In my work, I removed label leakage from claim features.", ev)
    assert personal_sentence_ok("Boosting works.", ev)


def test_answer_technical_rewrites_once_when_the_reviewer_finds_an_error():
    from career_agent.longform.technical import answer_technical
    c = Corpus(KnowledgeBase([], {}, {}, {}, []))
    drafts = ["Bagging is sequential.", "Bagging is parallel."]
    writer = lambda p: drafts.pop(0)
    verdicts = [json.dumps({"claims": [{"claim": "Bagging is sequential.", "verdict": "incorrect", "correction": "Bagging is parallel."}]}),
                json.dumps({"claims": [{"claim": "Bagging is parallel.", "verdict": "correct"}]})]
    out = answer_technical("bagging vs boosting?", c, writer, lambda p: verdicts.pop(0))
    assert out["answer"] == "Bagging is parallel." and out["status"] == "corrected" and out["rewrites"] == 1


def test_a_doubted_claim_keeps_an_answer_out_of_checked():
    from career_agent.longform.technical import answer_technical
    c = Corpus(KnowledgeBase([], {}, {}, {}, []))
    verdict = json.dumps({"claims": [{"claim": "Boosting is useful on noisy data.", "verdict": "uncertain"},
                                     {"claim": "Boosting is sequential.", "verdict": "correct"}]})
    out = answer_technical("bagging vs boosting?", c, lambda p: "Boosting is sequential and useful on noisy data.", lambda p: verdict)
    assert out["status"] == "unsure" and out["uncertain_claims"] == ["Boosting is useful on noisy data."] and out["rewrites"] == 0
