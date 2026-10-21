"""The ad/decoy "Apply" arbiter (class C, job 31505) and the upsell-modal ladder
with its 2-strike degrade (class B, job 31867). Fake pages only: the arbiter's
pure table tests rank plain descriptor dicts, and dismiss_dialogs runs against a
locator stub in the spirit of the existing fake-page tests (test_filler_combobox)."""
import re

import pytest

from career_agent.browser.cta_arbiter import AD_HOST_FRAGMENTS, is_ad_like, rank, score


@pytest.fixture(autouse=True)
def _fresh_run_state():
    """dismiss_dialogs keeps run-scoped strike state in module globals (the _TRAIL precedent)."""
    import career_agent.browser.page_prep as pp

    def clear():
        pp._TRAIL.clear()
        pp._MODAL_ATTEMPTS.clear()
        pp._STUCK_NOTED.clear()

    clear()
    yield
    clear()


# --- class C: the scoring table ------------------------------------------

def test_ad_iframe_candidate_loses_to_the_sticky_apply_bar():
    # job 31505: the ad iframe sold an identically labeled "Apply Now" while the
    # job's real control was the site's own fixed bottom bar.
    bar = {"name": "Apply now", "ctx": {"sticky": True}}
    ad = {"name": "Apply Now", "frame_url": "https://securepubads.g.doubleclick.net/x",
          "ctx": {"small_frame": True}}
    assert score(ad) > 0 > score(bar)
    ranked = rank([ad, bar])
    assert ranked[0]["name"] == "Apply now" and ranked[-1]["name"] == "Apply Now"


def test_a_rotating_ad_host_that_skips_the_deny_still_loses_on_position():
    # the deny list can never be exhaustive; the sit/label features decide the tie
    bar = {"name": "Apply now"}
    ad = {"name": "Apply Now", "frame_url": "https://rotate-ads-9871.example/x",
          "ctx": {"small_frame": True}}
    assert score(ad) > score(bar) and rank([ad, bar])[0]["name"] == "Apply now"


def test_sponsored_marker_is_a_penalty_but_not_condemnation_alone():
    plain = {"name": "Careers"}
    marked = {"name": "Careers", "attrs": "class=sponsored"}
    assert score(marked) == score(plain) + 1.0
    assert not is_ad_like({"attrs": "data-ad-slot"})       # one +1 marker stays under the +2 threshold
    assert is_ad_like({"attrs": "id=div-gpt-ad-4"})        # ad machinery alone trips the deny threshold


def test_house_copy_and_frame_sits_stack_into_the_ranking():
    # house copy +1 (the doc's seed list), banner-sized +1, corner +1 — three
    # light signals stack to 3.0, past the +2 ad threshold, so the +6 demotion
    # caps the tile under every plain control (a house tile IS a decoy shell).
    tile = {"name": "Best resume service — Get started",
            "ctx": {"small_frame": True, "corner_frame": True}}
    assert score(tile) == pytest.approx(9.0)
    # machinery +2 and the "promoted" marker +1 (sold row plus the house word
    # row) stack to 4.0 → +6 cap → 10, then the real "Apply now" intent -5.
    unit = {"name": "Apply now, promoted", "attrs": "div-gpt-ad"}
    assert score(unit) == pytest.approx(5.0)


def test_apply_intent_pulls_a_control_below_neutral_and_sticky_down():
    assert score({"name": "Apply for this job"}) == pytest.approx(-5.0)
    assert score({"name": "Apply"}) == pytest.approx(-2.0)
    assert score({"name": "Apply now", "ctx": {"sticky": True}}) == score({"name": "Apply now"}) - 4.0


def test_a_banner_size_token_alone_is_a_light_signal():
    assert score({"attrs": "size:300x250"}) == pytest.approx(1.0)
    assert not is_ad_like({"attrs": "size:300x250"})


def test_no_candidates_change_nothing():
    assert rank([]) == []
    assert score({}) == 0.0
    assert not is_ad_like({})


def test_rank_ties_keep_the_caller_s_order_then_the_learned_phrase_order():
    a, b = {"name": "Apply now", "ref": "a"}, {"name": "Apply now", "ref": "b"}
    assert [c["ref"] for c in rank([a, b])] == ["a", "b"]
    from career_agent.browser.page_prep import _APPLY_ALLOW
    p, q = {"name": "Apply now", "ref": "p"}, {"name": "Apply for this job", "ref": "q"}
    assert [c["ref"] for c in rank([p, q], allow=_APPLY_ALLOW)] == ["q", "p"]


def test_one_ad_host_table_is_read_by_every_deny_path():
    from career_agent.browser import page_prep, perception
    for frag in AD_HOST_FRAGMENTS:
        assert page_prep._is_ad_frame(f"https://cdn.{frag}/frame.html"), frag
        assert perception.is_denied_frame(f"https://cdn.{frag}/frame.html"), frag
    assert not page_prep._is_ad_frame("https://boards.greenhouse.io/embed/job_app?for=acme")
    assert not perception.is_denied_frame("about:srcdoc")


def test_sit_flags_may_arrive_inline_or_as_page_ctx():
    sticky = {"name": "Apply now", "ctx": {"sticky": True}}
    assert score(sticky) == score({"name": "Apply now", "sticky": True})


# --- class C wiring: the drill's multi-candidate pick ---------------------

class _Frame:
    def __init__(self, url="", clickables=(), sit=()):
        self.url = url
        self._clickables, self._sit = clickables, sit

    def evaluate(self, js, arg=None):
        if "_affN" in js:                              # the clickable scan
            return [dict(c) for c in self._clickables]
        if "sticky" in js:                             # SIT_REPORT_JS
            return [dict(r) for r in self._sit]
        return ""


class _Page:
    def __init__(self, frames):
        self.frames = list(frames)
        self.viewport_size = {"width": 1280, "height": 800}


def test_drill_arbitration_prefers_a_sticky_bar_over_a_better_phrased_button():
    from career_agent.browser.page_prep import find_apply_affordance
    inline = {"name": "Apply for this job", "role": "button", "ref": '[data-aff="a0"]'}
    bar = {"name": "Apply now", "role": "button", "ref": '[data-aff="a1"]'}
    sit = [{"ref": '[data-aff="a1"]', "sticky": True, "fixed_bottom": True,
            "in_footer": False, "ad_mark": ""}]
    assert find_apply_affordance(_Page([_Frame(clickables=[inline, bar], sit=sit)]))["name"] == "Apply now"
    # with no sit answers the label priorities stand exactly as before the arbiter
    page = _Page([_Frame(clickables=[inline, bar])])
    assert find_apply_affordance(page)["name"] == "Apply for this job"


def test_single_or_no_candidate_is_todays_pick_down_to_the_keys():
    from career_agent.browser.page_prep import find_apply_affordance
    only = {"name": "Apply now", "role": "link", "ref": '[data-aff="a0"]'}
    aff = find_apply_affordance(_Page([_Frame(clickables=[only])]))
    assert (aff["name"], aff["role"], aff["frame"]) == ("Apply now", "link", 0)
    assert find_apply_affordance(_Page([_Frame()])) is None


def test_the_ad_frame_deny_still_skips_the_frame_before_arbitration():
    from career_agent.browser.page_prep import find_apply_affordance
    main = {"name": "Apply now", "role": "button", "ref": '[data-aff="a0"]'}
    adframe = {"name": "Apply Now", "role": "button", "ref": '[data-aff="a9"]'}
    aff = find_apply_affordance(_Page([
        _Frame(clickables=[main]),
        _Frame(url="https://tpc.googlesyndication.com/safeframe/1", clickables=[adframe])]))
    assert aff["name"] == "Apply now" and aff["frame"] == 0


# --- class B: the upsell ladder under dismiss_dialogs ---------------------

class _Keyboard:
    def __init__(self, sink):
        self._sink = sink

    def press(self, key):
        self._sink.append(("escape", key))


class _Loc:
    first = property(lambda self: self)

    def __init__(self, count=0):
        self._n = count

    def count(self):
        return self._n


class _CloseLoc:
    first = property(lambda self: self)

    def __init__(self, effect):
        self._effect = effect

    def count(self):
        return 1

    def click(self, timeout=None):
        self._effect()


class _Button:
    def __init__(self, sink, name, effect):
        self.first = self
        self._sink, self.name, self._effect = sink, name, effect

    def count(self):
        return 1

    def click(self, timeout=None, no_wait_after=None):
        self._sink.append(("click", self.name))
        if self._effect:
            self._effect()


class _Dialog:
    def __init__(self, sink, text, buttons, *, fillable=0, close_x=False, ad_marked=False,
                 page=None, closes_on_click=False):
        self.first = self
        self._sink, self._text, self._buttons = sink, text, list(buttons)
        self.fillable, self.close_x, self.marked = fillable, close_x, ad_marked
        self._page, self._closes = page, closes_on_click

    def count(self):
        return 1

    def inner_text(self, timeout=None):
        return self._text

    def locator(self, sel):
        if "a[href]" in sel:                       # names = dialog.locator("a[href], button")
            return self
        if "textarea" in sel or "select" in sel or "input" in sel:
            return _Loc(self.fillable)
        if "adsbygoogle" in sel:                   # _AD_DIALOG_CSS: ad machinery inside the modal
            return _Loc(1 if self.marked else 0)
        if "aria-label" in sel:                    # _CLOSE_X_CSS: the icon-only close
            if not self.close_x:
                return _Loc(0)

            def close():
                self._sink.append(("click", "close ×"))
                if self._closes:
                    self._page.open = None

            return _CloseLoc(close)
        return _Loc(0)

    def all_inner_texts(self):
        return list(self._buttons)

    def get_by_role(self, role, name=None, exact=None):
        pat = getattr(name, "pattern", None)
        for b in self._buttons:
            if pat and re.fullmatch(pat, b, re.I):
                effect = (lambda: setattr(self._page, "open", None)) if self._closes else None
                return _Button(self._sink, b, effect)
        return _Loc(0)


class _ModalPage:
    """A tab whose role=dialog locator lives in `open` (None once the click removes it)."""

    def __init__(self, text, buttons, *, fillable=0, close_x=False, ad_marked=False,
                 closes_on_click=False):
        self.events = []
        self.keyboard = _Keyboard(self.events)
        self.url = "https://site.test/job/31867"
        self.open = _Dialog(self.events, text, buttons, fillable=fillable, close_x=close_x,
                            ad_marked=ad_marked, page=self, closes_on_click=closes_on_click)

    def locator(self, sel):
        return self.open if self.open and "role=dialog" in sel else _Loc(0)

    def inner_text(self, sel):                     # clicks.act's stable page signature
        return self.open._text if self.open else ""

    def wait_for_timeout(self, ms):
        pass


def test_upsell_with_a_named_exit_is_dismissed():
    page = _ModalPage("Generate an AI cover letter and stand out", ["No thanks"], closes_on_click=True)
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True
    assert ("click", "No thanks") in page.events


def test_upsell_without_a_named_exit_uses_the_close_icon():
    page = _ModalPage("Unlock premium resume tools today", [], close_x=True, closes_on_click=True)
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True
    assert ("click", "close ×") in page.events


def test_an_ad_marked_modal_is_escaped_never_handed_off():
    page = _ModalPage("Generate an AI cover letter", ["Apply now"], ad_marked=True)
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True           # Escape, not the ad's own Apply
    assert not any(e[0] == "click" for e in page.events)
    assert ("escape", "Escape") in page.events


def test_the_handoff_continue_modal_is_clicked_as_the_final_rung():
    # job 31867: the modal's ONLY named control skips the upsell and continues to
    # the application — clicking it beats the old six-in-a-row modal loop.
    page = _ModalPage("Don't let your application get lost in the pile — generate an AI cover letter",
                      ["I'm ready to apply"], closes_on_click=True)
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True
    assert ("click", "I'm ready to apply") in page.events


def test_an_apply_boundary_modal_without_upsell_copy_is_also_handed_off():
    # class (b): the continue button IS the site's own apply handoff
    page = _ModalPage("Ready to continue to the application?", ["I'm ready to apply"], closes_on_click=True)
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True
    assert ("click", "I'm ready to apply") in page.events


def test_a_two_control_upsell_never_auto_clicks_the_sell():
    page = _ModalPage("Boost your resume with the AI writer",
                      ["Generate cover letter", "I'm ready to apply"])
    from career_agent.browser.page_prep import dismiss_dialogs
    assert dismiss_dialogs(page) is True           # Escape: not the buy button
    assert not any(e[0] == "click" for e in page.events)
    assert ("escape", "Escape") in page.events


def test_two_identical_snapshots_stop_the_attempts_at_two():
    from career_agent.browser.page_prep import _MODAL_ATTEMPTS, dismiss_dialogs, take_trail
    page = _ModalPage("Generate an AI cover letter", ["No thanks"])   # the click never lands
    assert dismiss_dialogs(page) is True           # attempt 1
    assert dismiss_dialogs(page) is True           # attempt 2, then the degrade
    assert dismiss_dialogs(page) is False          # stuck: no third attempt
    assert [e for e in page.events if e[0] == "click"] == [("click", "No thanks")] * 2
    assert any(n.get("step") == "modal_stuck" for n in take_trail())
    assert _MODAL_ATTEMPTS[max(_MODAL_ATTEMPTS, key=_MODAL_ATTEMPTS.get, default="")] <= 2


def test_a_resolved_modal_rebuilds_strike_state_from_zero():
    from career_agent.browser.page_prep import _MODAL_ATTEMPTS, dismiss_dialogs
    page = _ModalPage("Session idle", ["Continue Working"], closes_on_click=True)
    assert dismiss_dialogs(page) is True
    assert dismiss_dialogs(page) is False                      # modal gone: nothing to dismiss
    assert not _MODAL_ATTEMPTS                                 # success never leaves a strike behind


def test_todays_rules_still_hold_for_idle_and_application_dialogs():
    from career_agent.browser.page_prep import dismiss_dialogs
    idle = _ModalPage("Your session is about to expire", ["Continue Working"], closes_on_click=True)
    assert dismiss_dialogs(idle) is True
    assert ("click", "Continue Working") in idle.events
    app = _ModalPage("Reach out to Chris", ["Close", "Send"], fillable=1)
    assert dismiss_dialogs(app) is False                       # the fillable form modal keeps its Close
    assert not any(e[0] == "click" for e in app.events)
