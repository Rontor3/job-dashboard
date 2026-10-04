import json
from pathlib import Path

import pytest

from career_agent.longform.kb import KnowledgeBase

FIXTURE = Path(__file__).parent / "fixtures" / "ingredients.json"

STORIES = {
    "story_looking_for": "I want to work on hard applied ML problems with real stakes.",
    "story_why_startups": "I like ownership and speed.",
    "story_proudest_work": "Shipping models people rely on every day.",
    "story_how_you_work": "I work in small teams with high ownership.",
    "story_problems": "Problems where data is messy and the cost of being wrong is real.",
}
PROJECT_STORIES = {
    "p-graph": "## problem\nFraud rings hid in plain sight.\n## hardest\nMaking the graph scale to millions of nodes.\n"
               "## result\nFound 40 rings in the first month.",
}
FACTS = {"current_title": "Data Scientist", "current_company": "Acme Corp", "years_experience": "3"}


@pytest.fixture
def kb():
    data = json.loads(FIXTURE.read_text())
    return KnowledgeBase(data["units"], dict(STORIES), dict(PROJECT_STORIES), dict(FACTS), data["skills_pool"])
