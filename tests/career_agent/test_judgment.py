from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience, Education
from career_agent.orchestrator.judgment import (
    JudgmentContext, profile_to_text, _is_sensitive, map_option,
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
