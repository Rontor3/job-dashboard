"""A drop-down repeating the label of the one before it is its next level (Indeed: Country, then 'Country' = state)."""
from career_agent.browser.form_model import Field
from career_agent.browser.perception import sub_levels


def test_a_repeated_country_dropdown_is_the_state():
    fs = [Field("#c", "select", "Country *", True, options=["India", "Japan"], purpose="country"),
          Field("#s", "select", "Country *", False, options=["Andhra Pradesh", "Maharashtra"], purpose="country",
                description="Which applies to you?"),
          Field("#x", "select", "Gender", False, options=["Male"], purpose="gender")]
    got = sub_levels(fs)
    assert [(f.label, f.purpose, f.description) for f in got[:2]] == [("Country *", "country", ""), ("State*", "state", "")]
    assert got[2].label == "Gender"


def test_two_different_dropdowns_are_left_alone():
    fs = [Field("#a", "select", "Country", True, options=["India"], purpose="country"),
          Field("#b", "select", "Notice period", True, options=["30 days"], purpose=None)]
    assert [f.label for f in sub_levels(fs)] == ["Country", "Notice period"]
