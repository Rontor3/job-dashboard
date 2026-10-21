"""What the filler types into a type-ahead, in order (filler._type_ahead_queries)."""
from career_agent.browser.filler import _type_ahead_queries


def test_a_long_name_is_tried_with_its_short_forms_before_the_place():
    qs = _type_ahead_queries("Indian Institute of Technology BHU, Varanasi")
    assert qs[0] == "Indian Institute of Technology BHU, Varanasi"
    assert qs.index("IIT BHU") < qs.index("Varanasi")                 # Greenhouse school search, live 2026-10-18
    assert "Indian Institute of Technology BHU" in qs


def test_an_address_is_tried_from_its_city():
    assert _type_ahead_queries("Santacruz (E), Mumbai")[:2] == ["Santacruz (E), Mumbai", "Mumbai"]
    assert _type_ahead_queries("Mumbai") == ["Mumbai"]
