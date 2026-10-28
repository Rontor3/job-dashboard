from types import SimpleNamespace as N
from career_agent.browser.form_model import guess_purpose
from career_agent.orchestrator.screen_review import map_screen


def test_a_bare_acknowledged_box_is_an_attestation():
    assert guess_purpose("Acknowledged", "checkbox") == "attestation"
    assert guess_purpose("NO", "checkbox") is None


def _box(label, required):
    return N(ref="#c", kind="checkbox", label=label, purpose="attestation", required=required, options=[],
             description="", section="", group=None, group_label="", input_type="", placeholder="", part_hint="")


def test_an_optional_data_notice_stays_unticked_and_a_required_one_is_ticked():
    prof = N(contact={}, experiences=[], education=[], skills=[])
    note = "Your application will trigger processing of your personal data by the data controller"
    ds, _ = map_screen([_box(note, False)], prof)
    assert [d.value for d in ds] == [None]
    ds, _ = map_screen([_box(note, True)], prof)
    assert [d.value for d in ds] == [True]
