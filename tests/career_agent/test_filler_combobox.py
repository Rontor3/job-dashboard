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
    def filter(self, has_text=None): return FakeOption(self.sink, has_text)
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


def test_browserdeps_fill_uses_its_option_matcher_for_synonyms():
    from career_agent.orchestrator.browser_deps import BrowserDeps
    page = FakeComboPage(["Man", "Woman", "Non-binary"])
    matcher = lambda label, value, options: "Man" if value == "Male" else None
    BrowserDeps(option_matcher=matcher).fill(page, [_combo("#g", "Gender", "Male")], revalidate=False)
    assert ("click_option", "Man") in page.events



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
    assert ("open", "#g") in page.events
    assert not any(e[0] == "click_option" for e in page.events)
    assert ("press", "Escape") not in page.events
