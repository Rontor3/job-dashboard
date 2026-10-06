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

def test_pick_advance_matches_welcome_screen_start_button():
    form = [Field("#b", "button", "Start", False, [], None, None)]
    assert pick_advance_label(form, is_last=False) == "Start"


def test_review_is_not_an_advance_button_on_a_screen_that_has_submit():
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator.advance import advance_names, has_control, pick_advance_label
    F = lambda *labels: [Field(f"b{i}", "button", l, False, [], None, None) for i, l in enumerate(labels)]
    last = F("Previous", "Review", "Submit")                    # stepper link "Review" + the real final button
    assert "review" not in advance_names(last) and not has_control(last, advance_names(last))
    assert pick_advance_label(last, is_last=False) == "Submit"
    assert pick_advance_label(F("Next", "Review"), is_last=False) == "Next"            # a mid-wizard page is unchanged
    assert pick_advance_label(F("Review"), is_last=False) == "Review"                  # "Review" alone is still the way on


def test_a_link_that_merely_contains_next_is_not_the_next_button():
    from career_agent.browser.form_model import Field
    from career_agent.orchestrator.advance import has_control, pick_advance_label, ADVANCE_NAMES
    F = lambda *labels: [Field(f"b{i}", "button", l, False, [], None, None) for i, l in enumerate(labels)]
    jobs_page = F("Next.js", "Next JS Developer", "Next.Js Developer", "Start a free trial", "Continue reading on the blog")
    assert not has_control(jobs_page, ADVANCE_NAMES) and pick_advance_label(jobs_page, is_last=False) is None
    for real in ("Next", "Next >", "Next step", "Continue", "Continue to review", "Save and continue", "Save & Continue", "Review", "Start application"):
        assert pick_advance_label(F(real), is_last=False) == real, real


def test_four_screens_without_a_single_field_stops_as_not_a_form():
    from types import SimpleNamespace
    from career_agent.orchestrator.graph import advance_node, _f2d
    from career_agent.browser.form_model import Field
    link = [_f2d(Field("l", "button", "Next JS Developer", False, [], None, None))]      # a job link, not a Next button
    state = {"steps": 4, "decisions": [], "form": link, "stopped_reason": None, "max_steps": 20, "do_submit": False}
    cfg = {"configurable": {"page": SimpleNamespace(url="https://x/jobs"), "deps": SimpleNamespace(), "human": None}}
    assert advance_node(state, cfg)["stopped_reason"] == "no_form_found"
