

def test_type_ahead_queries_fall_back_to_city():
    from career_agent.browser.filler import _type_ahead_queries
    assert _type_ahead_queries("Santacruz (E), Mumbai") == ["Santacruz (E), Mumbai", "Mumbai", "Santacruz (E)"]
    assert _type_ahead_queries("Pune") == ["Pune"]
