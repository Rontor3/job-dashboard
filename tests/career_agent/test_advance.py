from career_agent.browser.form_model import Field
from career_agent.orchestrator.advance import (
    screen_signature, changed, pick_advance_label, has_control, SUBMIT_NAMES,
)

def _f(label): return Field("#"+label, "text", label, False, [], None, None)
def _b(label): return Field("#"+label, "button", label, False, [], None, None)


def test_submit_matching_is_word_bounded():
    # substring-within-word must NOT count as a submit control
    assert has_control([_b("Confirmation email sent")], SUBMIT_NAMES) is False
    assert has_control([_b("Click to reapply later")], SUBMIT_NAMES) is False
    assert has_control([_b("Setup finished successfully")], SUBMIT_NAMES) is False
    # genuine submit labels still match
    assert has_control([_b("Submit application")], SUBMIT_NAMES) is True
    assert has_control([_b("Confirm")], SUBMIT_NAMES) is True

def test_signature_changes_when_labels_change():
    a = screen_signature("http://x/step1", [_f("Email")])
    b = screen_signature("http://x/step1", [_f("First name"), _f("Last name")])
    assert changed(a, b) is True
    assert changed(a, a) is False

def test_pick_advance_prefers_continue_then_submit():
    names = ["Continue", "Cancel"]
    form = [Field("#b", "button", n, False, [], None, None) for n in names]
    assert pick_advance_label(form, is_last=False) == "Continue"
    subm = [Field("#s", "button", "Submit application", False, [], None, None)]
    assert pick_advance_label(subm, is_last=True) == "Submit application"

def test_never_returns_back_or_cancel():
    form = [Field("#b", "button", "Back", False, [], None, None)]
    assert pick_advance_label(form, is_last=False) is None
