from job_dashboard.rank_io import apply_eligibility


def test_big_gap_caps_verdict_to_weak_fit():
    job = {"description": "Senior role. Requires 10 years of experience."}
    payload = {"verdict": "Strong Fit", "flags": {}, "strengths": [], "gaps": []}
    out = apply_eligibility(job, payload, candidate_years=2)
    assert out["verdict"] == "Weak Fit"
    assert out["flags"]["eligibility"] and "10" in out["flags"]["eligibility"][0]
    # original payload not mutated
    assert payload["verdict"] == "Strong Fit"


def test_eligible_job_unchanged():
    job = {"description": "ML engineer, 2+ years, hires remotely in India."}
    payload = {"verdict": "Strong Fit", "flags": {}}
    out = apply_eligibility(job, payload, candidate_years=2)
    assert out["verdict"] == "Strong Fit"
    assert "eligibility" not in out.get("flags", {})


def test_poor_fit_is_not_upranked_to_weak():
    # A job already worse than Weak Fit must NOT be raised to Weak Fit.
    job = {"description": "Requires 15 years of experience."}
    out = apply_eligibility(job, {"verdict": "Poor Fit", "flags": {}}, candidate_years=2)
    assert out["verdict"] == "Poor Fit"                 # not up-ranked
    assert out["flags"]["eligibility"]                   # still flagged


def test_none_job_does_not_raise():
    out = apply_eligibility(None, {"verdict": "Strong Fit", "flags": {}}, candidate_years=2)
    assert out["verdict"] == "Strong Fit"                # no description -> no demote


def test_non_dict_flags_wrapped():
    job = {"description": "Requires 12 years experience."}
    out = apply_eligibility(job, {"verdict": "Good Fit", "flags": None}, candidate_years=2)
    assert out["verdict"] == "Weak Fit" and isinstance(out["flags"], dict)
