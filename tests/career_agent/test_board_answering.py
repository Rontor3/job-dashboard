from career_agent.browser.form_model import Field
from career_agent.orchestrator.answering import answer_fields, record_answers
from career_agent.orchestrator.mapper import FillDecision


def _f(ref, label):
    return Field(ref, "text", label, True, [], None, None)


class Learn:
    def __init__(self):
        self.rec = []

    def recall(self, fields):
        hit = [f for f in fields if f.label == "Known"]
        return ([FillDecision(f.ref, f.kind, f.label, "42", "fill", "learned") for f in hit],
                [f for f in fields if f not in hit])

    def record(self, f, a):
        self.rec.append((f.label, a))


def test_ladder_order_recall_rules_judge(monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))
    judged = []

    def judge(needs):
        judged.extend(needs)
        return [FillDecision(needs[0].ref, "text", needs[0].label, "llm", "fill", "judge")], needs[1:], None

    d, needs = answer_fields([_f("a", "Known"), _f("b", "Why us"), _f("c", "Other")],
                             {"learn": Learn(), "profile": None, "judge_fn": judge})
    assert [x.value for x in d] == ["42", "llm"]
    assert [f.ref for f in needs] == ["c"]
    assert [f.ref for f in judged] == ["b", "c"]


def test_record_answers_router_skips_blank():
    calls = []

    class Router:
        def dispatch(self, op, p):
            calls.append((op, p["question"], p["answer"], p["event"]))

    record_answers([_f("a", "CTC"), _f("b", "Blank")], {"a": " 22 ", "b": "  "},
                   {"memory_router": Router()}, {"a": "edit"})
    assert calls == [("RECORD_FEEDBACK", "CTC", "22", "edit")]


def test_record_answers_falls_back_to_learn():
    learn = Learn()
    record_answers([_f("a", "CTC")], {"a": "22"}, {"learn": learn})
    assert learn.rec == [("CTC", "22")]



def test_unlabelled_widget_gets_a_readable_name_for_the_human():
    from career_agent.boards.run import _readable
    f = Field("#react-select-form-input--qualification.location.locationId-input", "text", "", False, [], None, None)
    assert _readable(f).label == "Location"
    assert _readable(_f("a", "Expected CTC")).label == "Expected CTC"
