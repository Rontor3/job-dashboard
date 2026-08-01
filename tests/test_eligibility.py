from job_dashboard.match.eligibility import (
    EligibilityResult, parse_required_years, candidate_years_from_profile,
    assess_eligibility,
)


def test_parse_required_years_variants():
    assert parse_required_years("10 years of exp") == 10
    assert parse_required_years("Looking for 5+ years in ML") == 5
    assert parse_required_years("3 to 7 years experience") == 7  # max
    assert parse_required_years("no numbers here") is None


def test_candidate_years_from_profile():
    assert candidate_years_from_profile("Data Scientist with 2+ years building ML") == 2
    assert candidate_years_from_profile("no years mentioned", default=1.5) == 1.5


def test_big_gap_demotes():
    r = assess_eligibility("Requires 10 years of experience.", candidate_years=2)
    assert isinstance(r, EligibilityResult) and r.demote
    assert any("10" in f and "experience" in f.lower() for f in r.flags)


def test_small_gap_does_not_demote():
    # requires 5, candidate 2 -> gap 3, not > threshold 3
    assert assess_eligibility("5+ years required", candidate_years=2).demote is False


def test_no_required_years_no_demote():
    assert assess_eligibility("Great ML role, join us!", candidate_years=2).demote is False


def test_region_excluded_demotes():
    r = assess_eligibility("Remote. Hires remotely in: United States only.",
                           candidate_years=2, candidate_region="India")
    assert r.demote and any("India" in f for f in r.flags)


def test_region_present_ok():
    r = assess_eligibility("Hires remotely in: India, United States.",
                           candidate_years=20, candidate_region="India")
    assert r.demote is False  # region present, no year gap


def test_universal_region_does_not_demote():
    # "Everywhere"/"Worldwide"/"Global" mean all regions INCLUDE India -> keep.
    for word in ("Everywhere", "Worldwide", "Global", "Anywhere"):
        r = assess_eligibility(f"Remote. Hires remotely in: {word}.",
                               candidate_years=2, candidate_region="India")
        assert r.demote is False, word


def test_never_raises_on_junk():
    assert assess_eligibility(None, candidate_years=None).demote is False
