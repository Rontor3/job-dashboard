

def test_prompt_keeps_projects_in_separate_blocks(tmp_path, monkeypatch):
    # The real ingredient bank is user data (gitignored data/) — the prompt test
    # must not depend on it. A tmp bank with two scored units plays the same role.
    import json as _json
    from job_dashboard.apply import screening
    bank = tmp_path / "ingredients.json"
    bank.write_text(_json.dumps({"units": [
        {"type": "project", "title": "Fraud Detector", "org": "Acme", "problem": "fraud at scale",
         "approach": "AWS graph features", "impact": ["chewed"], "source": "resume line A", "tags": ["fraud", "aws"]},
        {"type": "project", "title": "Memorize Bench", "org": "Self", "problem": "recall",
         "approach": "flashcards", "impact": ["kept"], "source": "resume line B", "tags": ["memory"]},
    ]}))
    monkeypatch.setattr(screening, "_INGREDIENTS", bank)
    p = screening._build_prompt({"title": "ML Engineer", "company": "X", "description": "fraud detection AWS"},
                                "Tell us about a project", "Name: n", None, "jd")
    assert "PROJECT 1 —" in p and "PROJECT 2 —" in p and "SEPARATE project" in p
    assert p.index("PROJECT 1 —") < p.index("PROJECT 2 —") < p.index("QUESTION:") + 10**6
