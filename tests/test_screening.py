import json


def test_prompt_keeps_projects_in_separate_blocks(tmp_path, monkeypatch):
    from job_dashboard.apply import screening
    bank = tmp_path / "ingredients.json"
    bank.write_text(json.dumps({"units": [
        {"type": "project", "title": "Fraud detection on AWS", "org": "A", "tags": ["fraud"], "tech": ["AWS"],
         "problem": "p", "approach": "a", "impact": ["i"], "source": "s"},
        {"type": "work_experience", "title": "Speech synthesis", "org": "B", "tags": ["tts"], "tech": ["PyTorch"],
         "problem": "p", "approach": "a", "impact": "i", "source": "s"},
        {"type": "education", "title": "B.Tech", "org": "C"},
    ]}))
    monkeypatch.setattr(screening, "_INGREDIENTS", bank)
    p = screening._build_prompt({"title": "ML Engineer", "company": "X", "description": "fraud detection AWS"},
                                "Tell us about a project", "Name: n", None, "jd")
    assert "PROJECT 1 —" in p and "PROJECT 2 —" in p and "SEPARATE project" in p
    assert p.index("PROJECT 1 — Fraud detection") < p.index("PROJECT 2 — Speech synthesis")
    assert "B.Tech" not in p                                      # education units are not projects
