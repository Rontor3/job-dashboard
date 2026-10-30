from career_agent.browser.form_model import Field
from career_agent.browser.perception import is_unlabeled, apply_vision_labels


def _f(ref, kind, label, options=None):
    return Field(ref, kind, label, False, options or [], None, None)


def test_is_unlabeled_flags_placeholder_and_empty():
    assert is_unlabeled(_f("#a", "combobox", "Start typing..."))
    assert is_unlabeled(_f("#b", "text", "Pick date..."))
    assert is_unlabeled(_f("#c", "text", ""))
    assert is_unlabeled(_f("#d", "combobox", "Select..."))
    # a checkbox whose only label is an option word -> the question is missing
    assert is_unlabeled(_f("#e", "checkbox", "No"))
    # genuinely labelled fields are NOT unlabeled
    assert not is_unlabeled(_f("#n", "text", "First Name"))
    assert not is_unlabeled(_f("#age", "combobox", "Please select your age category:*"))   # Walmart: a question, not a placeholder
    assert is_unlabeled(_f("#ph", "combobox", "Please select"))
    assert not is_unlabeled(_f("#tc", "checkbox", "I agree to the terms and conditions"))
    assert not is_unlabeled(_f("#g", "combobox", "Gender"))


def test_apply_vision_labels_updates_label_and_repurposes():
    form = [_f("#x", "combobox", "Start typing..."),
            _f("#y", "checkbox", "No"),
            _f("#n", "text", "First Name")]         # untouched
    out = apply_vision_labels(form, {"#x": "Current location", "#y": "Are you legally authorized to work in the US?"})
    d = {f.ref: f for f in out}
    assert d["#x"].label == "Current location" and d["#x"].purpose == "location"   # re-guessed
    assert d["#y"].label.startswith("Are you legally authorized")
    assert d["#y"].purpose == "work_authorization"
    assert d["#n"].label == "First Name"            # unchanged


def test_phone_without_country_code_is_the_number():
    from career_agent.browser.form_model import guess_purpose
    assert guess_purpose("Please confirm your 10-digit mobile phone number (without the country code) using numeric "
                         "values only", "text") == "phone"
    assert guess_purpose("Country Phone Code*", "combobox") == "phone_country_code"


def test_a_long_textarea_asking_for_your_number_is_still_the_phone():
    """Walmart draws the phone-confirm box as a textarea (live 2026-10-30): it was read as an essay prompt."""
    from career_agent.browser.form_model import guess_purpose
    label = ("Please confirm your 10-digit mobile phone number (without the country code) using numeric values only "
             "(no dashes, periods, parentheses, etc.). For example: 4795550101*")
    assert guess_purpose(label, "textarea") == "phone"
    assert guess_purpose("Tell us how you managed state and context across a long running agent project and what you "
                         "learned from it overall", "textarea") is None
