import pytest

from job_dashboard.match.profile_text import compose_profile_text

PROFILE_MD = """# Candidate Profile
## Technical Skills
- Python, ML
"""

EVAL_MD = """# Job Evaluation Framework
**Career goals:**
- Move into AI Engineer roles.
- Remote-first.

**Motivation filter:** ...
"""


def test_compose_includes_profile_and_career_goals(tmp_path):
    profile = tmp_path / "01.md"
    evaluation = tmp_path / "04.md"
    profile.write_text(PROFILE_MD)
    evaluation.write_text(EVAL_MD)

    result = compose_profile_text(profile, evaluation)

    assert "Python, ML" in result.text
    assert "Move into AI Engineer roles." in result.text
    assert "Motivation filter" not in result.text  # only the goals block, not the rubric
    assert len(result.hash) == 64


def test_hash_changes_when_profile_changes(tmp_path):
    profile = tmp_path / "01.md"
    evaluation = tmp_path / "04.md"
    profile.write_text(PROFILE_MD)
    evaluation.write_text(EVAL_MD)
    first = compose_profile_text(profile, evaluation)

    profile.write_text(PROFILE_MD + "- FastAPI\n")
    second = compose_profile_text(profile, evaluation)

    assert first.hash != second.hash


def test_missing_profile_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="/setup"):
        compose_profile_text(tmp_path / "nope.md", tmp_path / "also-nope.md")


def test_missing_evaluation_file_is_tolerated(tmp_path):
    profile = tmp_path / "01.md"
    profile.write_text(PROFILE_MD)

    result = compose_profile_text(profile, tmp_path / "absent.md")
    assert "Python, ML" in result.text
