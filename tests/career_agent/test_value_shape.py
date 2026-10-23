from career_agent.browser.value_shape import shape_value

NUM = {"type": "text", "placeholder": "Enter numerals only"}
MONTH = {"type": "month"}
DATE = {"type": "date"}
TEXT = {"type": "text", "placeholder": "Enter your city"}


def test_numerals_only_box_takes_a_plain_number():
    assert shape_value("35 LPA", NUM) == "3500000"
    assert shape_value("12 lakh", NUM) == "1200000"
    assert shape_value("1.2 Cr", NUM) == "12000000"
    assert shape_value("₹35,00,000", NUM) == "3500000"
    assert shape_value("$120k", NUM) == "120000"
    assert shape_value("12.5 lakhs p.a.", NUM) == "1250000"
    assert shape_value("1,20,000", {"type": "number"}) == "120000"


def test_numerals_only_detected_from_type_pattern_or_hint():
    assert shape_value("35 LPA", {"type": "number"}) == "3500000"
    assert shape_value("35 LPA", {"type": "text", "pattern": "[0-9]*"}) == "3500000"
    assert shape_value("35 LPA", {"type": "text", "hint": "Enter numbers only, no commas"}) == "3500000"


def test_unparseable_or_non_numeric_values_are_left_alone():
    assert shape_value("around 35 LPA-ish", NUM) == "around 35 LPA-ish"
    assert shape_value("+91 9876543210", NUM) == "+91 9876543210"    # a phone is not a unit-bearing money value


def test_text_fields_are_unchanged():
    assert shape_value("35 LPA", TEXT) == "35 LPA"
    assert shape_value("Pune", {}) == "Pune"


def test_month_box_takes_yyyy_mm():
    assert shape_value("July 2023", MONTH) == "2023-07"
    assert shape_value("Jul 2023", MONTH) == "2023-07"
    assert shape_value("07/2023", MONTH) == "2023-07"
    assert shape_value("2023-07", MONTH) == "2023-07"
    assert shape_value("15/07/2023", MONTH) == "2023-07"


def test_date_box_takes_yyyy_mm_dd_and_month_only_is_the_first():
    assert shape_value("July 2023", DATE) == "2023-07-01"
    assert shape_value("2023-07", DATE) == "2023-07-01"
    assert shape_value("15/07/2023", DATE) == "2023-07-15"
    assert shape_value("2023-07-15", DATE) == "2023-07-15"


def test_unparseable_date_is_left_for_the_box_to_reject():
    assert shape_value("sometime soon", MONTH) == "sometime soon"


def demo():
    test_numerals_only_box_takes_a_plain_number()
    test_month_box_takes_yyyy_mm()
    print("ok")


if __name__ == "__main__":
    demo()


def test_a_placeholder_date_pattern_shapes_the_date():
    """UI5 / SuccessFactors date boxes are text boxes whose placeholder is the pattern (Wipro, live 2026-10-23)."""
    from career_agent.browser.value_shape import date_mask_refuses, shape_value
    mdy = {"placeholder": "MM/DD/YYYY"}
    assert shape_value("July 2023", mdy) == "07/01/2023"
    assert shape_value("17/03/2001", mdy) == "03/17/2001"                 # a day-first profile date
    assert shape_value("17/03/2001", {"placeholder": "YYYY-MM-DD"}) == "2001-03-17"
    assert shape_value("Jul 2022", {"placeholder": "MM/YYYY"}) == "07/2022"
    assert date_mask_refuses("Present", mdy) and date_mask_refuses("2023", mdy)   # left blank, asked
    assert not date_mask_refuses("July 2023", mdy) and not date_mask_refuses("2023", {"placeholder": "Year"})
