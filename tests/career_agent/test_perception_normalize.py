from career_agent.browser.perception import to_form_model


def test_maps_purpose_and_preserves_fields():
    raw = [
        {"ref": "#name", "kind": "text", "label": "Full name",
         "required": True, "options": [], "group": None},
        {"ref": "#email", "kind": "email", "label": "Email",
         "required": True, "options": [], "group": None},
    ]
    fm = to_form_model(raw)
    assert [f.purpose for f in fm] == ["full_name", "email"]
    assert fm[0].required is True


def test_radio_inputs_collapse_into_one_group():
    raw = [
        {"ref": "#r1", "kind": "radio", "label": "Yes",
         "required": False, "options": [], "group": "authorized"},
        {"ref": "#r2", "kind": "radio", "label": "No",
         "required": False, "options": [], "group": "authorized"},
    ]
    fm = to_form_model(raw)
    assert len(fm) == 1
    g = fm[0]
    assert g.kind == "radio_group"
    assert g.ref == "group:authorized"
    assert set(g.options) == {"Yes", "No"}


def test_empty_input_yields_empty_model():
    assert to_form_model([]) == []


def test_disabled_and_readonly_fields_are_dropped():
    raw = [
        {"ref": "#live", "kind": "text", "label": "Full name",
         "required": False, "options": [], "group": None, "disabled": False},
        {"ref": "#decoy", "kind": "text", "label": "Full name",
         "required": False, "options": [], "group": None, "disabled": True},
    ]
    fm = to_form_model(raw)
    assert [f.ref for f in fm] == ["#live"]
