"""Verify that reach_node returning kind="password" routes to cred_provide,
not directly to perceive, and that the cred_provided flag prevents looping.
tailor_cv now runs BEFORE reach (classify→tailor_cv→reach→perceive) so
reach always routes to perceive after a successful form landing."""
from career_agent.orchestrator.graph import _route_reach, _route_classify, initial_state


def _state(**kwargs):
    s = initial_state("https://example.com")
    s.update(kwargs)
    return s


def test_reach_routes_to_cred_provide_on_password_wall():
    s = _state(kind="password", cred_provided=False)
    assert _route_reach(s) == "cred_provide"


def test_reach_routes_to_perceive_after_cred_provided():
    # Second reach call (after cred_provide + tailor_cv ran): goes to perceive
    s = _state(kind="password", cred_provided=True)
    assert _route_reach(s) == "perceive"


def test_reach_routes_to_perceive_on_normal_form():
    s = _state(kind="form", cred_provided=False)
    assert _route_reach(s) == "perceive"


def test_classify_routes_to_tailor_cv_not_reach():
    # classify now sends to tailor_cv (which then goes to reach)
    s = _state(kind="none")
    assert _route_classify(s) == "tailor_cv"


def test_initial_state_cred_provided_is_false():
    s = initial_state("https://example.com")
    assert s["cred_provided"] is False
