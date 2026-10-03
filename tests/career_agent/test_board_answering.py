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





def test_unlabelled_widget_gets_a_readable_name_for_the_human():
    from career_agent.boards.run import _readable
    f = Field("#react-select-form-input--qualification.location.locationId-input", "text", "", False, [], None, None)
    assert _readable(f).label == "Location"
    assert _readable(_f("a", "Expected CTC")).label == "Expected CTC"



def test_choice_statement_becomes_a_question():
    from career_agent.boards.run import _readable
    f = Field("group:loc", "radio_group", "This job does not support the locations on your profile.", False,
              ["I am currently in…", "I can relocate to…"], None, None)
    assert _readable(f).label.endswith("Which applies to you?")



def test_choice_with_trailing_value_is_one_question_with_both_answers():
    from career_agent.boards.run import _ask
    choice = Field("group:loc", "radio_group", "This job does not support the locations on your profile.", False,
                   ["I am currently in…", "I can relocate to…"], None, None)
    value = Field("#react-select-location-input", "text", "", False, [], None, None)
    asked = []

    class Human:
        def collect(self, fields):
            asked.append([f.label for f in fields])
            return {fields[0].ref: "2 New Delhi"}

        def get_events(self):
            return {}

    decisions, left = _ask([choice, value], {"human": Human()})
    assert len(asked) == 1 and "e.g." in asked[0][0]
    assert {d.ref: d.value for d in decisions} == {"group:loc": "I can relocate to…",
                                                   "#react-select-location-input": "New Delhi"}
    assert left == []



def test_bare_number_reply_gets_a_follow_up_for_the_place():
    from career_agent.boards.run import _ask
    choice = Field("group:loc", "radio_group", "Location?", False, ["I am currently in…", "I can relocate to…"], None, None)
    value = Field("#loc", "text", "", False, [], None, None)
    replies = iter(["2", "New Delhi"])
    asked = []

    class Human:
        def collect(self, fields):
            asked.append(fields[0].label)
            return {fields[0].ref: next(replies)}

        def get_events(self):
            return {}

    decisions, _ = _ask([choice, value], {"human": Human()})
    assert asked[1] == "I can relocate to — which place?"
    assert {d.ref: d.value for d in decisions} == {"group:loc": "I can relocate to…", "#loc": "New Delhi"}



def test_paired_location_is_answered_from_the_profile_without_asking():
    from types import SimpleNamespace as NS
    from career_agent.boards.run import _ask, _job_location
    assert _job_location("Salary\n₹10L\nLocation\nNew Delhi\nRemote work policy") == "New Delhi"
    choice = Field("group:loc", "radio_group", "x", False, ["I am currently in…", "I can relocate to…"], None, None)
    value = Field("#loc", "text", "", False, [], None, None)

    class NoHuman:
        def collect(self, fields):
            raise AssertionError("must not ask")

    prof = NS(contact={"willing_to_relocate": True, "location": "Mumbai, India"})
    d, left = _ask([choice, value], {"human": NoHuman(), "profile": prof, "job_location": "New Delhi"})
    assert {x.ref: x.value for x in d} == {"group:loc": "I can relocate to…", "#loc": "New Delhi"} and left == []
    prof.contact["willing_to_relocate"] = False
    d, _ = _ask([choice, value], {"human": NoHuman(), "profile": prof, "job_location": "New Delhi"})
    assert {x.ref: x.value for x in d} == {"group:loc": "I am currently in…", "#loc": "Mumbai"}
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
