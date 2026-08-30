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


def test_combobox_role_promotes_text_to_combobox():
    # A React "fake dropdown" is an <input> that reports role=combobox; it must
    # be typed as combobox (open+pick), not text (blind fill).
    raw = [
        {"ref": "#gender", "kind": "text", "label": "Gender", "required": False,
         "options": [], "group": None, "role": "combobox"},
        {"ref": "#state", "kind": "text", "label": "State", "required": False,
         "options": [], "group": None, "haspopup": "listbox"},
        {"ref": "#name", "kind": "text", "label": "Full name", "required": False,
         "options": [], "group": None},
    ]
    fm = to_form_model(raw)
    kinds = {f.ref: f.kind for f in fm}
    assert kinds["#gender"] == "combobox"
    assert kinds["#state"] == "combobox"
    assert kinds["#name"] == "text"          # plain text box unaffected
