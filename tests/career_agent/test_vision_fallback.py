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
