from career_agent.browser.form_model import Field
from career_agent.orchestrator.answering import answer_fields, record_answers
from career_agent.orchestrator.mapper import FillDecision


def _f(ref, label):
    return Field(ref, "text", label, True, [], None, None)


class Learn:
    def recall(self, fields):
        hit = [f for f in fields if f.label == "Known"]
        return ([FillDecision(f.ref, f.kind, f.label, "42", "fill", "qbank") for f in hit],
                [f for f in fields if f not in hit])


class QA:
    def __init__(self):
        self.log = []

    def trace_all(self, fields):
        self.log.append(("trace", [f.ref for f in fields]))

    def decision(self, d):
        self.log.append(("decision", d.ref))

    def needs(self, f):
        self.log.append(("needs", f.ref))

    def answered(self, f, a):
        self.log.append(("answered", f.ref, a))


def _judge(needs):
    return [FillDecision(needs[0].ref, "text", needs[0].label, "llm", "fill", "judge")], needs[1:], None


def test_ladder_order_bank_rules_judge(monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))
    d, needs = answer_fields([_f("a", "Known"), _f("b", "Why us"), _f("c", "Other")],
                             {"learn": Learn(), "profile": None, "judge_fn": _judge})
    assert [x.value for x in d] == ["42", "llm"]
    assert [f.ref for f in needs] == ["c"]


def test_ladder_ignores_memory_router(monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))

    class Router:
        def dispatch(self, *a):
            raise AssertionError("semantic tier must not be consulted")

    d, needs = answer_fields([_f("a", "Other")], {"memory_router": Router(), "profile": None})
    assert d == [] and [f.ref for f in needs] == ["a"]


def test_every_field_is_recorded_to_qa(monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))
    qa = QA()
    answer_fields([_f("a", "Known"), _f("b", "Other")], {"learn": Learn(), "profile": None, "qa": qa})
    assert qa.log == [("trace", ["a", "b"]), ("decision", "a"), ("needs", "b")]


def test_record_answers_keeps_them_per_application_only():
    qa = QA()
    record_answers([_f("a", "CTC"), _f("b", "Blank")], {"a": " 22 ", "b": "  "}, {"qa": qa})
    assert qa.log == [("answered", "a", "22")]
    record_answers([_f("a", "CTC")], {"a": "22"}, {})      # no recorder: nothing to do, no error
