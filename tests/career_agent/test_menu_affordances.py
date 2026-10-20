"""Menu-affordance structure: page chrome can't flood the field list and nested
menu items read as a parent → child path. Live class F 2026-10-20: a careers
page rendered 102 flat "fields" (all its nav buttons) while the Careers ▾
submenu items never stood out. Offline: fabricated rows exactly as _INPUT_JS
emits them after the container tagging."""
from career_agent.browser.perception import _MENU_CONTEXT_CAP, to_form_model, _structure_menu_rows


def _btn(label, container="", menu_path="", ref=None):
    return {"kind": "button", "label": label, "ref": ref or f"button:{label}",
            "container": container, "menu_path": menu_path}


def _fld(label, i):
    return {"kind": "text", "label": label, "ref": f"#f{i}", "required": False}


def test_chrome_buttons_are_capped_around_the_form():
    rows = [_fld("First name", i) for i in range(3)]
    rows += [_btn(f"Nav {i}", container="chrome") for i in range(102)]
    out = _structure_menu_rows(rows)
    chrome = [r for r in out if r.get("container") == "chrome"]
    assert len(chrome) == _MENU_CONTEXT_CAP                 # the flood capped
    assert [r["ref"] for r in out[:3]] == ["#f0", "#f1", "#f2"]   # main content first, untouched


def test_a_real_form_is_never_capped_even_by_a_hundred_rows():
    rows = [_fld(f"Q{i}", i) for i in range(120)]
    assert _structure_menu_rows(rows) == rows                # byte-identical passthrough


def test_menu_affordances_read_as_a_parent_child_path():
    rows = [
        _btn("Careers", container="chrome"),
        _btn("Benefits", container="menu", menu_path="Careers"),
        _btn("Working here", container="menu", menu_path="Careers"),
    ]
    out = _structure_menu_rows(rows)
    assert out[0]["label"] == "Careers"                      # chrome, kept under the cap
    assert out[1]["label"] == "Careers > Benefits"           # parent → child path
    assert out[2]["label"] == "Careers > Working here"
    assert len(out) == 3                                     # menu items are never capped


def test_a_menu_label_that_already_carries_its_path_is_untouched():
    p = _btn("Careers > Benefits", container="menu", menu_path="Careers")
    assert _structure_menu_rows([p])[0]["label"] == "Careers > Benefits"


def test_flow_words_are_not_nav_junk_even_in_chrome():
    rows = [_btn(f"Nav {i}", container="chrome") for i in range(20)]
    rows.insert(2, _btn("Next", container="chrome"))
    out = [r for r in _structure_menu_rows(rows) if r.get("label") == "Next"]
    assert len(out) == 1                                     # a chrome control that advances the flow survives the cap


def test_to_form_model_shows_the_hierarchy_and_the_cap():
    rows = [_fld("First name", 1)]
    rows += [_btn(f"Nav {i}", container="chrome") for i in range(40)]
    rows.append(_btn("Job openings", container="menu", menu_path="Careers"))
    fields = to_form_model(rows)
    nav = [f for f in fields if (f.label or "").startswith("Nav ")]
    assert len(nav) == _MENU_CONTEXT_CAP
    menu = [f for f in fields if "Job openings" in (f.label or "")]
    assert len(menu) == 1 and menu[0].label == "Careers > Job openings"
    assert len([f for f in fields if f.label == "First name"]) == 1


def test_rows_without_container_keys_behave_exactly_as_before():
    rows = [{"kind": "text", "label": "Email", "ref": "#e", "required": True},
            {"kind": "button", "label": "Continue", "ref": "button:Continue"}]
    out = _structure_menu_rows(rows)
    assert out == rows                                       # legacy callers: byte-identical
    fields = to_form_model(rows)
    assert [f.kind for f in fields] == ["text", "button"]
