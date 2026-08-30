from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.judgment import (
    JudgmentContext, profile_to_text, _is_sensitive, map_option, judge,
)


def _f(ref, label, purpose=None, kind="text", options=None, required=False):
    return Field(ref, kind, label, required, options or [], None, purpose)


def test_profile_to_text_includes_experience_and_skills():
    p = CandidateProfile(
        contact={"full_name": "Rakshit Singh"},
        experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", ["Built fraud models"])],
        education=[Education("IIT BHU", "B.Tech", "Ceramics")],
        skills=["Python", "SQL"])
    t = profile_to_text(p)
    assert "Rakshit Singh" in t and "Tata AIG" in t and "Data Scientist" in t
    assert "Built fraud models" in t and "Python" in t and "B.Tech" in t


def test_is_sensitive_flags_demographics_and_attestation():
    assert _is_sensitive(_f("#g", "Gender"))
    assert _is_sensitive(_f("#e", "Are you Hispanic/Latino?"))
    assert _is_sensitive(_f("#v", "Have you served in the armed forces?", purpose="veteran"))
    assert _is_sensitive(_f("#d", "Disability status"))
    assert _is_sensitive(_f("#a", "I certify this is true", purpose="attestation"))
    assert not _is_sensitive(_f("#q", "Why do you want this role?", kind="textarea"))


def test_map_option_picks_a_real_option_or_none():
    opts = ["High school", "Bachelor's degree", "Master's degree"]
    llm_ok = lambda prompt: "Bachelor's degree"
    assert map_option("Highest level of education", opts, "B.Tech from IIT", llm_ok) == "Bachelor's degree"
    llm_bad = lambda prompt: "PhD"
    assert map_option("Highest level of education", opts, "B.Tech", llm_bad) is None
    llm_none = lambda prompt: "NONE"
    assert map_option("Highest level of education", opts, "B.Tech", llm_none) is None
    # LLM wraps the choice in a sentence -> accept the single contained option
    llm_verbose = lambda prompt: "The candidate holds a Bachelor's degree (B.Tech)."
    assert map_option("Highest level of education", opts, "B.Tech", llm_verbose) == "Bachelor's degree"
    # reply mentions two options -> ambiguous -> escalate
    llm_ambig = lambda prompt: "Between Bachelor's degree and Master's degree, likely the former."
    assert map_option("Highest level of education", opts, "B.Tech", llm_ambig) is None


def test_judge_answers_freetext_flags_and_escalates_sensitive():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme", "description": "..."},
                          profile_text="Rakshit, Data Scientist at Tata AIG")
    freetext = _f("#q", "What interests you about this role?", kind="text", required=True)
    gender = _f("#g", "Gender", kind="text")
    llm = lambda prompt: "I'm excited about Acme because of my ML work at Tata AIG."
    answered, still_need, flagged = judge([freetext, gender], ctx, llm, cap=6)
    d = {x.ref: x for x in answered}
    assert d["#q"].source == "judgment" and "Acme" in d["#q"].value
    assert "#g" in {f.ref for f in still_need}          # sensitive -> escalate
    assert "#q" not in {f.ref for f in still_need}


def test_judge_escalates_textarea_for_editable_draft():
    # Essays (textareas) are never auto-committed — they escalate so the
    # collector can offer the human an editable draft. llm is never called.
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    essay = _f("#why", "Why do you want to work here?", kind="textarea", required=True)
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "auto essay"
    answered, still_need, flagged = judge([essay], ctx, llm)
    assert "#why" in {f.ref for f in still_need}
    assert "#why" not in {x.ref for x in answered}
    assert called["n"] == 0


def test_judge_never_answers_a_search_box():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    search = _f("#s", "Search", kind="text")
    called = {"n": 0}
    def llm(prompt): called["n"] += 1; return "some answer"
    answered, still_need, flagged = judge([search], ctx, llm)
    assert "#s" in {f.ref for f in still_need}     # escalated, not answered
    assert called["n"] == 0                        # llm never called for a search box


def test_judge_maps_enum_or_escalates():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="B.Tech IIT")
    edu = _f("#edu", "Highest level of education", kind="select",
             options=["Bachelor's degree", "Master's degree"], required=True)
    llm = lambda prompt: "Bachelor's degree"
    answered, still_need, flagged = judge([edu], ctx, llm)
    assert {x.ref: x for x in answered}["#edu"].value == "Bachelor's degree"


def test_judge_respects_cap():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q1 = _f("#q1", "One-word motivation?", kind="text", required=True)
    q2 = _f("#q2", "Another short answer?", kind="text", required=True)
    llm = lambda prompt: "grounded answer"
    answered, still_need, flagged = judge([q1, q2], ctx, llm, cap=1)
    assert len(answered) == 1 and len(still_need) == 1   # cap hit -> one escalates


def test_judge_never_raises_on_llm_failure():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "Short answer?", kind="text", required=True)
    def boom(prompt): raise RuntimeError("ollama down")
    answered, still_need, flagged = judge([q], ctx, boom, cap=6)
    assert "#q" in ({x.ref for x in answered} | {f.ref for f in still_need})


def test_judge_tier3_orchestrator_answers_weak_freetext():
    ctx = JudgmentContext(job={"title": "DS", "company": "Acme"}, profile_text="x")
    q = _f("#q", "Short answer?", kind="text", required=True)
    def boom(prompt): raise RuntimeError("ollama down")   # -> general_fallback (weak)
    orch = lambda items: {it["ref"]: "Orchestrator-drafted answer." for it in items}
    answered, still_need, flagged = judge([q], ctx, boom, cap=6, orchestrator=orch)
    d = {x.ref: x for x in answered}
    assert d["#q"].source == "orchestrator" and "Orchestrator" in d["#q"].value
