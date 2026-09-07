from career_agent.orchestrator.screen_review import _coerce_option


def test_exact_and_yesno():
    assert _coerce_option("India", ["USA", "India", "UK"]) == "India"
    assert _coerce_option("indIA", ["USA", "India"]) == "India"        # case-insensitive
    assert _coerce_option("Yes", ["No, thanks", "Yes, I agree"]) == "Yes, I agree"
    assert _coerce_option("No", ["Yes", "No"]) == "No"


def test_numeric_range_experience():
    opts = ["0-2 years", "3-5 years", "6-10 years", "10+ years"]
    assert _coerce_option("3", opts) == "3-5 years"        # the ZF case
    assert _coerce_option(3, opts) == "3-5 years"          # int value too
    assert _coerce_option("7", opts) == "6-10 years"
    assert _coerce_option("15", opts) == "10+ years"       # 15 in [10, inf)


def test_numeric_range_phrasings():
    assert _coerce_option("12", ["Less than 5", "5-10", "More than 10"]) == "More than 10"
    assert _coerce_option("1", ["Less than 2 years", "2-5 years"]) == "Less than 2 years"
    assert _coerce_option("2", ["Up to 2", "3+"]) == "Up to 2"


def test_word_containment():
    assert _coerce_option("Bachelors", ["Masters Degree", "Bachelors Degree"]) == "Bachelors Degree"


def test_option_subset_of_value():
    # "Mumbai, India" -> the city option (the Prismforce location case)
    assert _coerce_option("Mumbai, India", ["Bangalore", "Mumbai", "Delhi"]) == "Mumbai"
    # prefer the longest matching option (city over bare country)
    assert _coerce_option("Mumbai, India", ["India", "Mumbai"]) == "Mumbai"


def test_no_false_positive_or_match():
    assert _coerce_option("3", ["13-15 years", "20+ years"]) is None   # 3 in neither band
    assert _coerce_option("Xyz", ["Alpha", "Beta"]) is None
    assert _coerce_option("", ["Anything"]) is None
