"""Optional AI-drafted boxes are cleared so a form whose other answers are all known can go out (2026-10-25)."""
from career_agent.browser import filler


class Loc:
    def __init__(self, box): self.box = box; self.first = self
    def evaluate(self, js, timeout=None):
        return self.box.get("tick", False) if "checkbox" in js else self.box["optional"]
    def is_checked(self, timeout=None): return self.box.get("checked", False)
    def fill(self, v, timeout=None): self.box["value"] = v


class Target:
    def __init__(self, boxes): self.boxes = boxes
    def locator(self, sel): return Loc(self.boxes[sel])


def _setup(monkeypatch, boxes):
    t = Target(boxes)
    monkeypatch.setattr(filler, "frame_target", lambda page, ref: (t, ref))
    monkeypatch.setattr(filler, "field_value", lambda target, sel: boxes[sel]["value"])


def test_only_optional_judgment_text_boxes_are_spare(monkeypatch):
    _setup(monkeypatch, {"#msg": {"optional": True, "value": "Hi"}, "#essay": {"optional": False, "value": "x"},
                         "#name": {"optional": True, "value": "R"}})
    ds = [{"ref": "#msg", "kind": "textarea", "label": "Message", "source": "judgment"},
          {"ref": "#essay", "kind": "textarea", "label": "Why us", "source": "judgment"},
          {"ref": "#name", "kind": "text", "label": "Name", "source": "qbank"}]
    assert [d["ref"] for d in filler.optional_ai_boxes(None, ds)] == ["#msg"]


def test_a_starred_label_is_never_optional(monkeypatch):
    _setup(monkeypatch, {"#q": {"optional": True, "value": "x"}})
    assert filler.optional_ai_boxes(None, [{"ref": "#q", "kind": "text", "label": "Cover note *", "source": "judgment"}]) == []


def test_clear_reports_success_only_when_empty(monkeypatch):
    boxes = {"#msg": {"optional": True, "value": "Hi"}}
    _setup(monkeypatch, boxes)
    assert filler.clear_boxes(None, [{"ref": "#msg"}]) and boxes["#msg"]["value"] == ""


def test_only_empty_optional_boxes_are_skipped(monkeypatch):
    _setup(monkeypatch, {"#web": {"optional": True, "value": ""}, "#req": {"optional": False, "value": ""},
                         "#full": {"optional": True, "value": "x"}})
    assert filler.optional_empty(None, ["#web", "#req", "#full"]) == ["#web"]


def test_an_optional_unticked_notice_is_skipped_but_a_required_one_is_not(monkeypatch):
    _setup(monkeypatch, {"#notice": {"optional": True, "tick": True, "value": "on"},
                         "#must": {"optional": False, "tick": True, "value": "on"},
                         "#ticked": {"optional": True, "tick": True, "checked": True, "value": "on"}})
    assert filler.optional_empty(None, ["#notice", "#must", "#ticked"]) == ["#notice"]
