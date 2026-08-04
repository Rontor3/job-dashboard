from job_dashboard.resume.resume_llm import regenerate_block


def test_returns_alternatives_from_fake_llm():
    fake = lambda p: "1. Built **fraud** ML cutting cost 20%\n2. Shipped real-time scoring"
    alts = regenerate_block("experience", "DS", ["Built fraud models", "cut cost 20%"],
                            "Need ML engineer", "3 years fraud ML, cut cost 20%", llm=fake, n=2)
    assert len(alts) >= 1 and all(isinstance(a, list) for a in alts)


def test_unsupported_number_becomes_placeholder():
    fake = lambda p: "1. Boosted revenue by 87% overnight"
    alts = regenerate_block("experience", "DS", ["Improved revenue"],
                            "jd", "worked on revenue models", llm=fake, n=1)
    flat = " ".join(alts[0]) if alts else ""
    assert "87%" not in flat
    assert "[add number]" in flat


def test_llm_failure_returns_empty_never_raises():
    def boom(p): raise RuntimeError("ollama down")
    assert regenerate_block("experience", "DS", ["x"], "jd", "prof", llm=boom) == []


def test_unit_blind_number_not_grounded_by_different_unit():
    # A "$20 stipend" in the source must NOT legitimize a fabricated "20%".
    fake = lambda p: "1. Cut costs by 20% through automation"
    alts = regenerate_block("experience", "DS", ["Received a $20 stipend"], "jd",
                            "worked on cost projects", llm=fake, n=1)
    flat = " ".join(alts[0]) if alts else ""
    assert "20%" not in flat and "[add number]" in flat
