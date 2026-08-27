from career_agent.browser.form_model import Field
from career_agent.orchestrator.advance import screen_signature, changed, pick_advance_label

def _f(label): return Field("#"+label, "text", label, False, [], None, None)

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
