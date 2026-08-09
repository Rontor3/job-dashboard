import pytest

from job_dashboard.match.relevance import is_target_role


@pytest.mark.parametrize("title", [
    "Machine Learning Engineer", "Senior Data Scientist", "Staff Data Scientist",
    "AI Engineer", "AI/ML Engineer", "LLM Engineer", "NLP Engineer",
    "MLOps Engineer", "Applied Scientist", "Computer Vision Engineer",
    "Deep Learning Researcher", "Lead ML Scientist", "Generative AI Engineer",
])
def test_keeps_target_roles(title):
    assert is_target_role(title)


@pytest.mark.parametrize("title", [
    "Sales Jedi", "SaaS Product Support Jedi", "Senior Quality Engineer",
    "Healthcare Virtual Assistant Registered Nurse", "Drivers wanted",
    "Legal Receptionist Fully", "Product Manager", "Content Reviewer",
    "Area Manager Freelance", "Barista", "", None,
])
def test_drops_off_target(title):
    assert not is_target_role(title)


def test_ml_ai_tokens_not_false_matched():
    # bare tokens must be word-bounded, not substrings
    assert not is_target_role("HTML Developer")     # 'ml' inside html
    assert not is_target_role("Air Traffic Controller")  # 'ai' inside air
    assert is_target_role("ML Lead")
    assert is_target_role("AI Engineer")
