"""The applied-state detector: a board's own page can say the job is already
applied for before the engine hunts for an entry. Live naukri 2026-10-20 (class
D): a green 'Applied' badge styled as a span, no form anywhere, queue reason
'unconfirmed' — the engine only learned it via assist reasoning. Offline: fake
pages, no Playwright."""
from career_agent.boards.run import _posting_state


class _Page:
    """Answers only the probes _posting_state uses; unknown evaluates are inert."""
    def __init__(self, body="", badge=False, button_applied=False, has_form=False):
        self.body = body
        self.badge = badge
        self.button_applied = button_applied
        self.has_form = has_form
    def evaluate(self, js, arg=None):
        if "span,div" in js:                    # the badge probe's leaf-element selector
            return self.badge
        if "role=dialog" in js:                 # _form_already_open
            return self.has_form
        if "querySelectorAll('button')" in js:  # _APPLIED_BUTTON_JS
            return self.button_applied
        if "document.body.innerText" in js:     # is_closed_posting's whole-body read
            return self.body
        return ""


def test_a_badge_with_no_form_stops_before_the_entry_hunt():
    out = _posting_state(_Page(badge=True), "")
    assert out == "already_applied_board_state"


def test_the_same_badge_beside_an_open_form_stays_untriaged():
    out = _posting_state(_Page(badge=True, has_form=True), "")
    assert out is None                       # the form itself decides; the run proceeds


def test_no_badge_is_no_state():
    assert _posting_state(_Page(), "") is None


def test_the_older_evidence_paths_keep_their_names():
    assert _posting_state(_Page(button_applied=True), "") == "already_applied"
    assert _posting_state(_Page(), "You've already applied to this job") == "already_applied"
