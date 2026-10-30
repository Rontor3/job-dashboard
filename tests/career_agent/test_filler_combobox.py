from career_agent.orchestrator.mapper import FillDecision
from career_agent.browser.filler import apply_decisions


class FakeOption:
    def __init__(self, sink, name): self.sink = sink; self.name = name; self.first = self
    def click(self, timeout=None): self.sink.append(("click_option", self.name))


class FakeKeyboard:
    def __init__(self, sink): self.sink = sink
    def press(self, key): self.sink.append(("press", key))


class FakeScope:                       # both a listbox locator and the page fallback
    def __init__(self, sink, options, in_dialog=False, typed_options=None):
        self.sink = sink; self._options = options
        self._in_dialog = in_dialog; self._typed = typed_options
    first = property(lambda self: self)
    def locator(self, sel): return self          # scope.locator("[role=option]")
    def all_text_contents(self): return list(self._options)
    def filter(self, has_text=None):             # a whole-text pattern resolves to the one option it matches
        if hasattr(has_text, "search"):
            has_text = next((o for o in self._options if has_text.search(o)), None)
        return FakeOption(self.sink, has_text)
    def evaluate(self, js): return self._in_dialog
    def is_visible(self): return True
    def fill(self, value, timeout=None):         # type-ahead: options load after typing
        self.sink.append(("type", value))
        if self._typed is not None:
            self._options = self._typed
    def get_by_role(self, role, name=None, exact=None):
        self.sink.append(("pick", name)); return FakeOption(self.sink, name)


class FakeComboPage:
    def __init__(self, options, lb_id="react-select-x-listbox", in_dialog=False, typed_options=None):
        self._options = options; self._lb = lb_id
        self.events = []; self.keyboard = FakeKeyboard(self.events)
        self._scope = FakeScope(self.events, options, in_dialog, typed_options)
    def click(self, ref, timeout=None): self.events.append(("open", ref))
    def wait_for_timeout(self, ms): pass
    def get_attribute(self, ref, attr): return self._lb
    def locator(self, sel): return self._scope


def _combo(ref, label, value):
    return FillDecision(ref, "combobox", label, value, "combobox", "resume")


def test_combobox_exact_option_clicked():
    page = FakeComboPage(["Male", "Female", "Decline To Self Identify"])
    apply_decisions(page, [_combo("#gender", "Gender", "Male")])
    assert ("open", "#gender") in page.events
    assert ("click_option", "Male") in page.events


def test_combobox_word_match_via_coerce():
    page = FakeComboPage(["Yes, I have a disability", "No, I do not have a disability"])
    apply_decisions(page, [_combo("#d", "Disability", "No")])
    assert ("click_option", "No, I do not have a disability") in page.events


def test_combobox_synonym_uses_matcher():
    page = FakeComboPage(["Man", "Woman", "Non-binary"])
    matcher = lambda label, value, options: "Man" if value == "Male" else None
    apply_decisions(page, [_combo("#g", "Gender", "Male")], matcher=matcher)
    assert ("click_option", "Man") in page.events


def test_combobox_no_match_closes_without_click():
    page = FakeComboPage(["Man", "Woman"])
    apply_decisions(page, [_combo("#g", "Gender", "Male")])   # no matcher, no coerce hit
    assert ("open", "#g") in page.events
    assert not any(e[0] == "click_option" for e in page.events)
    assert ("press", "Escape") in page.events                 # left blank for human


def test_browserdeps_threads_matcher_to_filler(monkeypatch):
    from career_agent.orchestrator.browser_deps import BrowserDeps
    seen = {}
    def fake_apply(page, decisions, matcher=None): seen["matcher"] = matcher
    monkeypatch.setattr("career_agent.browser.filler.apply_decisions", fake_apply)
    m = lambda label, value, options: None
    BrowserDeps(option_matcher=m).fill(object(), [])
    assert seen["matcher"] is m



def test_type_ahead_combobox_types_then_picks():
    # Live Wellfound location picker: no options until the value is typed.
    page = FakeComboPage([], typed_options=["New Delhi, Delhi", "New York"])
    apply_decisions(page, [_combo("#loc", "", "New Delhi")])
    assert ("type", "New Delhi") in page.events
    assert ("click_option", "New Delhi, Delhi") in page.events


def test_no_match_inside_a_modal_does_not_press_escape():
    # Escape would close the whole application modal (Wellfound).
    page = FakeComboPage(["Man", "Woman"], in_dialog=True)
    apply_decisions(page, [_combo("#g", "Gender", "Male")])
    assert ("press", "Escape") not in page.events


def test_an_unlisted_value_takes_the_lists_others_option():
    """Wipro's BTech majors have no 'Ceramic Engineering' but list 'OTHERS' (live 2026-10-23); 'Other' did not match it,
    and a judge then picked 'Computer Science'."""
    from career_agent.browser.filler import _OTHER_OPTION
    assert _OTHER_OPTION.search("OTHERS") and _OTHER_OPTION.search("Other") and not _OTHER_OPTION.search("Otherwise")


def test_an_option_differing_only_by_dots_and_spaces_is_the_value():
    from career_agent.orchestrator.screen_review import _coerce_option
    assert _coerce_option("B. Tech", ["B. Pharm", "B.Sc (Tech)", "BTech"]) == "BTech"


def test_an_unlisted_answer_takes_its_banked_stand_in():
    """Opella's Workday 'How Did You Hear About Us?' lists no 'Job Board'; the bank's synonym 'Company Portal' is
    the user's chosen stand-in (2026-10-25), tried before any model match."""
    from career_agent.browser.filler import apply_decisions
    page = FakeComboPage(["Company Portal", "Events", "Referral", "Social Network"])
    d = FillDecision("#src", "combobox", "How Did You Hear About Us?", "Job Board", "combobox", "qbank",
                     alternatives=("Company Portal",))
    apply_decisions(page, [d])
    assert ("click_option", "Company Portal") in page.events


def test_a_category_with_one_option_commits_that_option():
    """Workday 'How Did You Hear About Us?': 'Company Portal' is a category whose only option is 'Company Career Site'
    (Opella, live 2026-10-25). No option matches the answer, there is no 'Other' — the lone option is the pick."""
    from career_agent.browser.filler import _drill_to_leaf
    clicks = []

    class Scope:
        def locator(self, sel): return self
        def all_text_contents(self): return ["Company Career Site", "Company Career Site"]
        def filter(self, has_text=None):
            return type("O", (), {"first": type("F", (), {"click": lambda s, timeout=None: clicks.append(has_text.pattern)})()})()

    page = type("P", (), {"wait_for_timeout": lambda s, ms: None})()
    _drill_to_leaf(page, Scope(), ["Company Portal", "Events"], lambda opts: None)
    import re
    assert clicks and re.search(clicks[0], "Company Career Site")


def test_a_category_falls_back_to_its_own_other_entry():
    """Workday 'Job Board' opens CareerBuilder, Indeed, LinkedIn, Naukri, 'Other Job Board' (Walmart, live 2026-10-29):
    none fits 'Job Board', and the catch-all is 'Other Job Board', not a bare 'Other' — it is still the pick."""
    import re
    from career_agent.browser.filler import _drill_to_leaf
    clicks = []

    class Scope:
        def locator(self, sel): return self
        def all_text_contents(self): return ["CareerBuilder", "Indeed", "LinkedIn", "Naukri", "Other Job Board"]
        def filter(self, has_text=None):
            return type("O", (), {"first": type("F", (), {"click": lambda s, timeout=None: clicks.append(has_text.pattern)})()})()

    page = type("P", (), {"wait_for_timeout": lambda s, ms: None})()
    _drill_to_leaf(page, Scope(), ["Job Board", "Company Portal"], lambda opts: None)
    assert clicks and re.search(clicks[0], "Other Job Board")


def test_a_slow_sub_list_is_waited_for():
    """Walmart Workday (live 2026-10-30): 'Job Board's leaves were still empty at 400 ms, so nothing was picked."""
    import re
    from career_agent.browser.filler import _drill_to_leaf
    clicks, reads = [], []

    class Scope:
        def locator(self, sel): return self
        def all_text_contents(self):
            reads.append(1)
            return [] if len(reads) < 4 else ["Indeed", "LinkedIn", "Other Job Board"]
        def filter(self, has_text=None):
            return type("O", (), {"first": type("F", (), {"click": lambda s, timeout=None: clicks.append(has_text.pattern)})()})()

    page = type("P", (), {"wait_for_timeout": lambda s, ms: None})()
    _drill_to_leaf(page, Scope(), ["Job Board", "Other"], lambda opts: None)
    assert clicks and re.search(clicks[0], "Other Job Board")
