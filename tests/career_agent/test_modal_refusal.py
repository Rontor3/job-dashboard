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


# ── walk-level stop: the walker's own advance click is what opens the refusal ──
# Live validation (f5be553, job 31505 Upstart, 2026-10-20): reach exited "none", the walker
# [click]'ed 'Apply now' only mid-walk, the "Apply to Upstart" modal appeared, and the run
# burned every step at "0 filled" to no_form_found. reach can never see it; the walk must.

REFUSAL = {"head": "Apply to Upstart",
           "quote": "Update your working permit information | Update profile | Find similar jobs"}


def _field(ref, label, kind="button", purpose=None):
    from career_agent.browser.form_model import Field
    return Field(ref, kind, label, False, [], None, purpose)


def _modal_screen():
    from career_agent.browser.form_model import Field
    return [Field(f"#b{i}", "button", name, False, [], None, None)
            for i, name in enumerate(("Close", "Update your working permit information",
                                      "Update profile", "Find similar jobs"))]


class RefusalJsPage:
    """A page standing in for one DOM state: evaluate() answers the real _APPLY_REFUSAL_JS
    verdict (`ret`) — the canned dict/None IS the JS's verdict for this DOM — and evaluates
    everything else to None, like a page carrying no matching structure. `ret_after_click`
    re-points the verdict when the walker's own advance click lands (deps.click): the modal
    only comes to exist then, exactly as it did live."""
    def __init__(self, ret=REFUSAL, ret_after_click=None):
        self.url = "https://himalayas.app/jobs/12999-applied-scientist"
        self.ret, self.ret_after_click = ret, ret_after_click
    def evaluate(self, js, *args):
        if "applyPat" not in js:
            return None
        if isinstance(self.ret, Exception):
            raise self.ret
        return self.ret
    def wait_for_timeout(self, ms):
        pass
    def inner_text(self, sel):
        return ""


class _Deps:
    """Canned screens; the walker's advance click is what flips to the next screen
    (the house pattern from test_entry_choose_apply._Deps). The click also flips the
    page's refusal verdict (the modal exists only from that click on)."""
    def __init__(self, screens):
        self._screens, self._i = screens, 0
    def snapshot(self, page, scroll=True):
        return self._screens[min(self._i, len(self._screens) - 1)]
    def gate(self, page):
        return "none"
    def fill(self, page, decisions):
        pass
    def click(self, page, label):
        self._i += 1
        if getattr(page, "ret_after_click", None) is not None:
            page.ret = page.ret_after_click
    def url(self, page):
        return f"http://x/step{self._i}"


class _Human:
    def approve(self, card):
        return True
    def remote_solve(self, page, gate, on_link):
        return True
    def collect(self, fields):
        return {}


def test_walk_stops_site_refused_when_the_walker_clicks_into_the_refusal():
    """(a) The walker advances at 0 filled (its only control is a Continue), and its own click
    opens the refusal modal: the walk stops at the modal's first sight — before any fill work —
    quoting the site's words through the same stop path the reach boundary uses."""
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile
    from career_agent.browser import page_prep as pp
    pp.take_trail()
    out = walk(RefusalJsPage(ret=None, ret_after_click=REFUSAL), CandidateProfile(), _Human(),
               _Deps([[_field("#adv", "Continue")], _modal_screen()]))
    assert out["stopped_reason"] == "site_refused"
    assert out["site_said"].startswith("Update your working permit") and len(out["site_said"]) <= 240
    assert out["screens"] == 2 and out["submitted"] is False      # stopped ON the modal screen, no extra pass
    refused = [t for t in pp.take_trail() if t.get("step") == "site_refused"]
    assert len(refused) == 1 and refused[0]["modal"] == "Apply to Upstart"


def test_a_walk_that_already_filled_something_is_not_a_refusal():
    """(b) Same modal, but screen 1 filled a field: a modal mid-form is not the site refusing —
    the walk keeps walking (here it runs out of controls and ends as it always did)."""
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile
    out = walk(RefusalJsPage(ret=None, ret_after_click=REFUSAL),
               CandidateProfile(contact={"full_name": "Rakshit"}), _Human(),
               _Deps([[_field("#n", "Full name", "text", "full_name"), _field("#adv", "Continue")],
                      _modal_screen()]))
    assert out["stopped_reason"] == "no_advance_control"          # walked on, not site_refused


def test_a_walk_facing_a_continue_cta_modal_keeps_flowing():
    """(c) The modal has no input but a Continue hand-off (the real JS answers None — gate (c)):
    never a refusal; the existing modal_kept flow decides what happens."""
    from career_agent.orchestrator.step_engine import walk
    from career_agent.memory.candidate_profile import CandidateProfile
    out = walk(RefusalJsPage(ret=None), CandidateProfile(), _Human(),
               _Deps([[_field("#adv", "Continue")], _modal_screen()]))
    assert out["stopped_reason"] != "site_refused"


def _graph_cfg(deps, page):
    return {"configurable": {"page": page, "deps": deps, "human": _Human()}}


def _graph_state(**over):
    from career_agent.orchestrator.graph import initial_state
    s = initial_state("https://himalayas.app/jobs/12999-applied-scientist")
    s.update(over)
    return s


def test_graph_perceive_stops_site_refused_with_the_sites_words():
    """The LangGraph engine's boundary — perceive after the walker's fill/advance cycle saw the
    modal at 0 decisions: stopped_reason + site_said ride the state to the run's result dict."""
    from career_agent.orchestrator.graph import perceive_node
    out = perceive_node(_graph_state(), _graph_cfg(_Deps([_modal_screen()]), RefusalJsPage()))
    assert out["stopped_reason"] == "site_refused"
    assert out["site_said"].startswith("Update your working permit") and len(out["site_said"]) <= 240


def test_graph_perceive_with_a_decision_already_made_is_never_a_refusal():
    from career_agent.orchestrator.graph import perceive_node
    st = _graph_state(decisions=[{"ref": "#n", "kind": "text", "label": "Full name",
                                  "value": "Rakshit", "action": "fill", "source": "profile"}])
    out = perceive_node(st, _graph_cfg(_Deps([_modal_screen()]), RefusalJsPage()))
    assert out.get("stopped_reason") is None
    assert [f["ref"] for f in out["form"]] == [f.ref for f in _modal_screen()]


def test_graph_perceive_with_a_continue_cta_modal_is_not_a_refusal():
    from career_agent.orchestrator.graph import perceive_node
    out = perceive_node(_graph_state(), _graph_cfg(_Deps([_modal_screen()]), RefusalJsPage(ret=None)))
    assert out.get("stopped_reason") is None and out["form"]
