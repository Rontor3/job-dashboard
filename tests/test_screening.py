

def test_prompt_keeps_projects_in_separate_blocks():
    from job_dashboard.apply.screening import _build_prompt
    p = _build_prompt({"title": "ML Engineer", "company": "X", "description": "fraud detection AWS"},
                      "Tell us about a project", "Name: n", None, "jd")
    assert "PROJECT 1 —" in p and "PROJECT 2 —" in p and "SEPARATE project" in p
    assert p.index("PROJECT 1 —") < p.index("PROJECT 2 —") < p.index("QUESTION:") + 10**6
