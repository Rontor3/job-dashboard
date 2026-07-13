import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

PROFILE_FILE = _REPO_ROOT / ".claude/skills/ai-job-search/skills/job-application-assistant/01-candidate-profile.md"
EVALUATION_FILE = _REPO_ROOT / ".claude/skills/ai-job-search/skills/job-application-assistant/04-job-evaluation.md"


@dataclass
class ProfileText:
    text: str
    hash: str


def compose_profile_text(profile_file=PROFILE_FILE, evaluation_file=EVALUATION_FILE):
    profile_file = Path(profile_file)
    if not profile_file.exists():
        raise FileNotFoundError(
            f"Profile file not found: {profile_file}. Run /setup to generate it first."
        )
    text = profile_file.read_text(encoding="utf-8")
    goals = _career_goals_block(Path(evaluation_file))
    if goals:
        text += "\n\n## Target Roles & Career Goals\n" + goals
    return ProfileText(text=text, hash=hashlib.sha256(text.encode()).hexdigest())


def _career_goals_block(evaluation_file):
    """Extract only the '**Career goals:**' bullet list — not the whole rubric."""
    if not evaluation_file.exists():
        return ""
    content = evaluation_file.read_text(encoding="utf-8")
    match = re.search(r"\*\*Career goals:\*\*\n((?:- .*\n)+)", content)
    return match.group(1) if match else ""
