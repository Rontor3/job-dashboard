from career_agent.browser.form_model import guess_purpose
from career_agent.orchestrator.standard_answers import answer


def test_purposes_split_sponsorship_from_authorization():
    assert guess_purpose("Will you require visa sponsorship?", "select") == "visa_sponsorship"
    assert guess_purpose("Are you legally authorized to work in the US?", "select") == "work_authorization"
    assert guess_purpose("Do you have any relatives employed here?", "select") == "prior_contact"


def test_answer_sponsorship_and_contact():
    assert answer("visa_sponsorship", "Will you require sponsorship?") == "Yes"
    assert answer("prior_contact", "Do you know anyone at the company?") == "No"


def test_answer_work_auth_is_jurisdiction_aware():
    assert answer("work_authorization", "Authorized to work in India?") == "Yes"
    assert answer("work_authorization", "Authorized to work in the United States?") == "No"
    assert answer("work_authorization", "Authorized to work in the UK?") == "No"
    assert answer("work_authorization", "Are you legally authorized to work?") is None
