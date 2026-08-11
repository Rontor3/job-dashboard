from job_dashboard.resume.resume_llm import suggest_skills
from job_dashboard.resume.segments import load_segments


def test_only_suggests_skills_present_in_context():
    # LLM returns a mix: two terms in the text (Docker, FastAPI), one NOT in
    # the text (Kubernetes — fabricated), one already listed (Python).
    fake = lambda _p: "Docker, Kubernetes, FastAPI, Python"
    context = "Built RoamMate with FastAPI backend, containerized with Docker Compose."
    out = suggest_skills(context, existing=["Python"], llm=fake)
    assert "Docker" in out and "FastAPI" in out
    assert "Kubernetes" not in out   # not in context -> dropped (no fabrication)
    assert "Python" not in out       # already listed -> skipped


def test_empty_context_returns_empty():
    assert suggest_skills("", existing=[], llm=lambda _p: "Docker") == []


def test_llm_failure_never_raises():
    def boom(_p):
        raise RuntimeError("down")
    assert suggest_skills("real text with Docker", llm=boom) == []


def test_default_skills_are_the_three_verbatim_categories():
    segs = {s.id: s for s in load_segments()}
    defaults = [s for s in segs.values() if s.kind == "skills" and s.default]
    titles = {s.title for s in defaults}
    assert titles == {
        "Programming & Technologies",
        "Machine Learning & Data Science",
        "Professional Skills",
    }
    # the tailored groups are opt-in (default: false)
    assert segs["skills-genai-llm"].default is False
