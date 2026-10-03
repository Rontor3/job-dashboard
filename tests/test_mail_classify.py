import pytest

from job_dashboard.mail_classify import classify, keyword_classify


@pytest.mark.parametrize("subject, body, category, round_", [
    ("Your application to Acme", "Thank you for applying. We have received your application.", "acknowledgement", None),
    ("Interview invitation – ML Engineer", "We'd like to schedule a call for the technical round.", "interview", None),
    ("Next steps", "You've cleared round 1. The second round is with the hiring manager.", "interview", 2),
    ("Update on your application", "Unfortunately we will not be moving forward. We regret to inform you.", "rejected", None),
    ("Regarding your interview", "We regret to inform you we've decided to move forward with other candidates.", "rejected", None),
    ("Offer of employment", "We are pleased to offer you the position. Offer letter attached.", "offer", None),
    ("Complete your assessment", "Please take the HackerRank coding test within 3 days.", "assessment", None),
    ("Weekly digest", "Ten jobs you may like", "other", None),
])
def test_keyword_rules(subject, body, category, round_):
    got = keyword_classify(subject, body)
    assert got["category"] == category and got["round"] == round_


def test_final_round_and_ordinals():
    assert keyword_classify("Final interview", "Please join us for the final round.")["round"] is None
    assert keyword_classify("Interview", "This is your third round of interviews")["round"] == 3


def test_llm_answer_is_used_when_valid():
    llm = lambda prompt: 'Sure! {"category": "interview", "round": 2, "summary": "Panel on Friday"} done'
    got = classify(llm, "Next steps", "see you friday", company="Acme", title="ML")
    assert got == {"category": "interview", "round": 2, "summary": "Panel on Friday", "by": "llm"}


@pytest.mark.parametrize("llm", [
    lambda p: "I cannot help",                                      # no JSON
    lambda p: '{"category": "party", "round": 1}',                  # unknown category
    lambda p: (_ for _ in ()).throw(ConnectionError("ollama down")),  # model not running
    None,
])
def test_falls_back_to_keywords_when_the_model_is_unusable(llm):
    got = classify(llm, "Interview invitation", "We'd like to schedule an interview", company="Acme", title="ML")
    assert got["category"] == "interview" and got["by"] == "rules"


def test_prompt_carries_company_and_job_and_trims_the_body():
    seen = {}

    def llm(prompt):
        seen["p"] = prompt
        return '{"category": "other", "round": null, "summary": ""}'

    classify(llm, "Hi", "x" * 10000, company="Acme AI", title="ML Engineer")
    assert "Acme AI" in seen["p"] and "ML Engineer" in seen["p"] and len(seen["p"]) < 5000
