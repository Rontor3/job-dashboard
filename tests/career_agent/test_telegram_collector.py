from career_agent.browser.form_model import Field
from career_agent.integrations.telegram.collector import TelegramCollector


class FakeClient:
    def __init__(self, replies): self.sent = []; self._replies = list(replies)
    def send_message(self, text, buttons=None): self.sent.append(text); return 1
    def poll_text(self, timeout_s): return self._replies.pop(0) if self._replies else None


def _f(ref, kind, label, options=None):
    return Field(ref, kind, label, True, options or [], None, None)


def _collector(client, drafter=None):
    return TelegramCollector(client, drafter=drafter, deadline_s=4,
                             poll_interval_s=1, sleep=lambda s: None)


def test_dropdown_numbered_and_number_reply_maps_to_option():
    c = FakeClient(["2"])
    out = _collector(c)([_f("#loc", "select", "Preferred Location", ["NY", "Jersey City", "Chicago"])])
    assert out == {"#loc": "Jersey City"}
    assert "1) NY" in c.sent[0] and "2) Jersey City" in c.sent[0]   # numbered list shown


def test_checkbox_yes_no():
    c = FakeClient(["yes"])
    out = _collector(c)([_f("#tc", "checkbox", "Subscribe to updates?")])
    assert out == {"#tc": "Yes"}


def test_textarea_uses_draft_on_ok():
    c = FakeClient(["ok"])
    drafter = lambda label: "JPMorgan's payments data work fits my ML background."
    out = _collector(c, drafter)([_f("#why", "textarea", "Why do you want to work here?")])
    assert out["#why"].startswith("JPMorgan")
    assert "Suggested:" in c.sent[0]                                # draft shown for editing


def test_textarea_edit_overrides_draft():
    c = FakeClient(["Actually, I admire the fraud-analytics team."])
    drafter = lambda label: "generic draft"
    out = _collector(c, drafter)([_f("#why", "textarea", "Why us?")])
    assert out["#why"] == "Actually, I admire the fraud-analytics team."


def test_combobox_free_text_typed_value():
    c = FakeClient(["Male"])
    out = _collector(c)([_f("#g", "combobox", "Gender")])
    assert out == {"#g": "Male"}


def test_file_field_is_not_asked():
    c = FakeClient([])
    out = _collector(c)([_f("#cv", "file", "Cover Letter")])
    assert out == {}
    assert "browser" in c.sent[0].lower()                          # told to attach in browser


def test_dropdown_no_match_skips():
    c = FakeClient(["banana"])
    out = _collector(c)([_f("#loc", "select", "Location", ["NY", "SF"])])
    assert out == {}                                               # unmatched -> not filled
