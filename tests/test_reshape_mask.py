"""A wrongly-filled field must be REFORMED, not re-typed.

The site drew its red box on a value we already put there (a phone with a country code
into a 10-digit box, a mask the placeholder states). The refill used to send the same
value again with real keystrokes — the fill was never the problem, the shape was."""
from src.career_agent.browser.validation import reformatted_value, reshape_mask


def test_placeholder_mask_phone():
    m = {"placeholder": "(###) ###-####"}
    assert reformatted_value("+91 98765 43210", m) == "(987) 654-3210"


def test_placeholder_mask_date_skeleton():
    m = {"placeholder": "MM/DD/YYYY"}
    # digits fill the mask left-to-right (calendar-order conversion is the entry-date
    # override's job — there we KNOW the semantics, here we only know the shape)
    assert reformatted_value("15.03.1998", m) == "15/03/1998"


def test_pattern_quantifier_bare_digits():
    m = {"pattern": "[0-9]{10}", "type": "tel"}
    assert reformatted_value("+91 98765 43210", m) == "9198765432"


def test_d_backslash_d_pattern():
    m = {"pattern": r"\d{6}"}
    assert reformatted_value("PIN 560103", m) == "560103"


def test_short_digits_gives_up():
    # needs 10 digits, has 6 — the human decides, we do not invent
    assert reformatted_value("987654", {"pattern": "[0-9]{10}"}) == ""


def test_maxlength_truncation():
    assert reformatted_value("an answer far too long for the box", {"maxlength": "10"}) == "an answer "
    # a value that fits is left alone (empty = no reform)
    assert reformatted_value("short", {"maxlength": "10"}) == ""


def test_no_contract_no_reform():
    assert reformatted_value("+91 98765 43210", {}) == ""


def test_reshape_mask_pure():
    assert reshape_mask("9876543210", "000-000-0000") == "987-654-3210"
    assert reshape_mask("031998", "MM/YYYY") == "03/1998"
    assert reshape_mask("x", "") == ""
    # placeholder with prose is not a skeleton — refuse rather than mangle
    assert reshape_mask("9876543210", "e.g. (555) 000-0000") == ""
