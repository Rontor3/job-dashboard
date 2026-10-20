"""S1-a (himalayas 2026-10-20, live CDP probes): after the walker clicks 'Apply now', the site
answers with an "Apply to Upstart" modal (~512×440) that has ZERO input/select/textarea elements
and only Close / "Update your working permit information" / "Update profile" / "Find similar
jobs" as clickables. The old run walked that formless state (the walk saw the modal's 4 buttons
as rows, 0 filled per step) for ~110 s and ended no_form_found. The refusal is the site saying
no — reach must stop there and the run must escalate, quoting the site's own words.

The FakePage pattern: evaluate() returns exactly what the real _APPLY_REFUSAL_JS computes for a
named DOM state (the canned dict/None IS the JS verdict; these tests pin the Python wiring)."""
from career_agent.browser.page_prep import _APPLY_MODAL_RE, _APPLY_REFUSAL_JS, _kept_modal_refusal


class RefusingPage:
    """A page standing in for one DOM state: `ret` is what _APPLY_REFUSAL_JS would return for it
    (None when one of its three gates refuses the label), or raise to emulate a torn page."""
    def __init__(self, ret):
        self.ret, self.calls = ret, []
    def evaluate(self, js, *args):
        self.calls.append((js, args))
        if isinstance(self.ret, Exception):
            raise self.ret
        return self.ret


def test_the_formless_apply_modal_is_a_refusal_dict():
    """Himalayas' exact modal: no field, head matches the apply vocabulary, only Close /
    Update-profile links / Find-similar-jobs behind it -> the site itself refusing."""
    p = RefusingPage({"head": "Apply to Upstart",
                      "quote": "Update your working permit information | Update profile | Find similar jobs"})
    d = _kept_modal_refusal(p)
    assert d == {"head": "Apply to Upstart",
                 "quote": "Update your working permit information | Update profile | Find similar jobs"}
    assert len(p.calls) == 1
    js, args = p.calls[0]
    assert js is _APPLY_REFUSAL_JS
    assert args[0] == _APPLY_MODAL_RE.pattern          # the head is judged against the site's own apply wording


def test_a_modal_with_a_visible_input_is_never_a_refusal():
    """JS gate (a): any visible input/select/textarea inside the dialog -> None — that modal is
    the application (or delegable) and stays on the existing modal_kept / walk flow."""
    assert _kept_modal_refusal(RefusingPage(None)) is None


def test_a_modal_with_a_continue_cta_is_never_a_refusal():
    """JS gate (c): a clickable named like a way on (Continue/Submit/Sign in/...) means the
    no-inputs modal hands off to another surface — modal_kept proceeds, never site_refused."""
    assert _kept_modal_refusal(RefusingPage(None)) is None


def test_an_empty_or_malformed_js_answer_is_not_a_refusal():
    assert _kept_modal_refusal(RefusingPage({"head": "", "quote": "Update profile"})) is None
    assert _kept_modal_refusal(RefusingPage({"head": "Apply to Upstart"})) is None
    assert _kept_modal_refusal(RefusingPage({"head": "Apply to Upstart", "quote": None})) is None
    assert _kept_modal_refusal(RefusingPage("not a dict")) is None


def test_a_torn_page_is_not_a_refusal():
    assert _kept_modal_refusal(RefusingPage(RuntimeError("navigating away"))) is None


def test_the_refusal_js_carries_its_three_gates():
    """The FakePage fakes the JS verdict; this pins the DOM contract the JS must keep implementing:
    the biggest visible dialog, the no-fields gate, the no-way-on vocab, and the quote/head shape."""
    js = _APPLY_REFUSAL_JS
    assert "[role=dialog],[role=alertdialog]" in js
    assert "input,select,textarea" in js               # gate (a)
    assert "new RegExp(applyPat, 'i')" in js and "applyPat" in js   # gate (b) uses _APPLY_MODAL_RE's pattern
    for w in ("apply", "continue", "next", "submit", "start", "sign", "create", "register"):
        assert w in js                                 # gate (c)'s proceed vocabulary
    assert "600" in js and "200" in js                 # quote cap and the >=200×200 dialog size


def test_a_head_not_resembling_an_apply_is_not_a_refusal():
    "Gate (b): e.g. a consent titled 'We value your privacy' -> None (the old dismiss flow decides)."
    assert _kept_modal_refusal(RefusingPage(None)) is None


class ReachPage:
    """A page already at its end state the whole drill: evaluate() answers the refusal JS."""
    def __init__(self, ret):
        self.url = "https://himalayas.app/jobs/12999-applied-scientist"
        self.ret = ret
    def evaluate(self, js, *args):
        return self.ret
    def wait_for_timeout(self, ms):
        pass


def _stub_reach_looks(monkeypatch, classify="none"):
    """Freeze every look _reach makes except the code under test: no form, no affordance left
    to follow, nothing else to try — reach falls through to the tail that returns the status."""
    from career_agent.browser import page_prep as pp
    monkeypatch.setattr(pp, "prepare", lambda pg: None)
    monkeypatch.setattr(pp, "classify_entry", lambda pg, status=None: classify)
    monkeypatch.setattr(pp, "is_application_form", lambda pg: False)
    monkeypatch.setattr(pp, "find_apply_affordance", lambda pg, exclude=(), prefer=(): None)
    monkeypatch.setattr(pp, "_manual_option_hop", lambda pg: False)
    monkeypatch.setattr(pp, "_is_wizard_step", lambda pg: False)
    monkeypatch.setattr(pp, "_try_url_variants", lambda pg: None)
    monkeypatch.setattr(pp, "_JOB_TITLE", "")
    return pp


def test_reach_returns_site_refused_when_the_kept_modal_refuses(monkeypatch):
    pp = _stub_reach_looks(monkeypatch)
    pp.take_trail()
    pg = ReachPage({"head": "Apply to Upstart",
                    "quote": "Update your working permit information and Update profile, or Find similar jobs"
                             + " (the site's own words)" * 30})
    active, status = pp.reach_application_form(pg)
    assert status == "site_refused" and active is pg
    trail = pp.take_trail()
    steps = [t.get("step") for t in trail]
    assert "site_refused" in steps and steps[-1] == "reach_end"
    refused = next(t for t in trail if t.get("step") == "site_refused")
    assert refused["modal"] == "Apply to Upstart"      # head passes under the 60-char cap unchanged
    assert len(refused["quote"]) <= 160 and refused["quote"].startswith("Update your working permit")


def test_a_not_refusing_modal_keeps_the_old_status_path(monkeypatch):
    """A modal that keeps drawing (its JS verdict is None — a field or a Continue CTA behind it):
    reach returns classify_entry's own verdict as before, never site_refused."""
    pp = _stub_reach_looks(monkeypatch, classify="none")
    pp.take_trail()
    _, status = pp.reach_application_form(ReachPage(None))
    assert status == "none"
    assert "site_refused" not in [t.get("step") for t in pp.take_trail()]


def test_a_real_form_reached_still_wins_over_a_stale_refusal_read(monkeypatch):
    """Order guard: if the drill did arrive on a form, that status is returned before the refusal
    helper is even asked — a stale refusal verdict from a leftover modal can never mask a form."""
    pp = _stub_reach_looks(monkeypatch)
    monkeypatch.setattr(pp, "is_application_form", lambda pg: True)
    pp.take_trail()
    _, status = pp.reach_application_form(ReachPage({"head": "Apply to Upstart",
                                                     "quote": "Update your working permit information"}))
    assert status == "form"
    assert "site_refused" not in [t.get("step") for t in pp.take_trail()]
