from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile, Experience
from career_agent.orchestrator.screen_review import map_screen, apply_answers

P = CandidateProfile(contact={"full_name": "Rakshit", "email": "r@x.com"},
                     experiences=[Experience("Tata AIG", "Data Scientist", "2023", "Present", [])],
                     skills=["Python"])

def _f(ref, label, purpose, required=False, kind="text"):
    return Field(ref, kind, label, required, [], None, purpose)

def test_fills_known_and_flags_unknown():
    form = [_f("#n", "Full name", "full_name"),
            _f("#emp", "Employer", "employer"),
            _f("#q", "Why do you want this job?", None, required=True, kind="textarea"),
            _f("#missing", "Portfolio URL", "portfolio_url", required=True)]
    decisions, needs = map_screen(form, P)
    d = {x.ref: x for x in decisions}
    assert d["#n"].value == "Rakshit" and d["#emp"].value == "Tata AIG"
    refs = {f.ref for f in needs}
    assert "#q" in refs          # novel required question -> human
    assert "#missing" in refs    # required, no profile value -> human

def test_apply_answers():
    needs = [_f("#q", "Why?", None, required=True, kind="textarea")]
    decisions = apply_answers(needs, {"#q": "Because I love ML."})
    assert decisions[0].value == "Because I love ML." and decisions[0].action == "fill"
