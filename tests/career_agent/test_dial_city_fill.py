"""Dial-code select gets the country code (not the number); a city box takes the city alone; no required field
leaves a screen undecided."""
from career_agent.browser.form_model import Field
from career_agent.memory.candidate_profile import CandidateProfile
from career_agent.orchestrator.answering import answer_fields
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.screen_review import map_screen


def _profile(phone="7565052330"):
    return CandidateProfile(contact={"phone": phone})


_DIAL = Field(ref="#cc", kind="select", label="Country Phone Code *", required=True,
              options=["Select a country", "India (+91)", "United States (+1)"], purpose="phone_country_code")


def test_dial_code_select_gets_country_code_not_number():
    decisions, needs = map_screen([_DIAL], _profile("+91 7565052330"))
    assert needs == []
    assert [(d.ref, d.value) for d in decisions] == [("#cc", "India (+91)")]


def test_dial_code_select_without_saved_prefix_escalates_not_dropped():
    decisions, needs = map_screen([_DIAL], _profile("7565052330"))
    assert decisions == [] and [n.ref for n in needs] == ["#cc"]


def test_phone_box_still_gets_the_number():
    f = Field(ref="#ph", kind="tel", label="Phone Number *", required=True, purpose="phone", input_type="tel")
    decisions, _ = map_screen([f], _profile("+91 7565052330"))
    assert [d.value for d in decisions] == ["7565052330"]


def test_required_field_without_decision_is_escalated_not_dropped():
    f = Field(ref="#x", kind="text", label="Mystery question *", required=True, purpose=None)
    decisions, needs = map_screen([f], _profile())
    assert decisions == [] and [n.ref for n in needs] == ["#x"]


class _StubRecall:
    """Question-bank stand-in: answers every field it is given with the stored value."""
    def __init__(self, value):
        self.value = value

    def recall(self, fields):
        return [FillDecision(f.ref, f.kind, f.label, self.value, "fill", "qbank") for f in fields], []


def test_city_box_takes_city_alone_from_stored_city_and_country():
    f = Field(ref="#city", kind="text", label="City *", required=True, purpose="city")
    decisions, _ = answer_fields([f], {"profile": _profile(), "learn": _StubRecall("Mumbai, India")})
    assert [d.value for d in decisions] == ["Mumbai"]


if __name__ == "__main__":
    test_dial_code_select_gets_country_code_not_number()
    test_phone_box_still_gets_the_number()
    test_required_field_without_decision_is_escalated_not_dropped()
    test_city_box_takes_city_alone_from_stored_city_and_country()
    print("ok")
