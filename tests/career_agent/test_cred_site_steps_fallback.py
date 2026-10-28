"""provide() must not report a site's own steps as done while the wall is still up: IBM's steps missed the IBMid
field (live 2026-10-22) and the run said handled:login on the login page. Still walled -> the generic path runs."""
import pytest

from career_agent.browser import credential_provider as cp
from career_agent.browser import page_prep


class FakePage:
    url = "https://login.ibm.com/authsvc/mtfim/sps/authsvc"


@pytest.fixture
def stubs(monkeypatch):
    calls = []
    for name in ("_ibm_register", "_ibm_login"):
        monkeypatch.setattr(cp, name, lambda page, cred, original_url=None, _n=name: calls.append(_n))
    monkeypatch.setattr(cp, "_try_guest_apply", lambda page: False)
    monkeypatch.setattr(cp, "_reveal_email_form", lambda page: None)
    monkeypatch.setattr(cp, "load_credential", lambda site, label="": {"username": "u@x.com", "password": "pw"})
    monkeypatch.setattr(cp, "_inline_email_verify_state", lambda page: False)
    monkeypatch.setattr(cp, "_is_email_first", lambda page: False)
    monkeypatch.setattr(cp, "_is_combined_form", lambda page: False)
    monkeypatch.setattr(cp, "_ensure_login_form", lambda page: None)
    monkeypatch.setattr(cp, "_is_login_form", lambda page: False)
    monkeypatch.setattr(cp, "_fill_wall", lambda page, gate, cred, site="": calls.append("generic_fill"))
    return calls


def test_wall_still_up_falls_through_to_generic(stubs, monkeypatch):
    monkeypatch.setattr(page_prep, "is_wall", lambda page, url: True)
    ok, action = cp._provide_attempt(FakePage(), "password", "login.ibm.com")
    assert stubs == ["_ibm_login", "generic_fill"]
    assert (ok, action) == (True, "login")


def test_wall_cleared_skips_generic(stubs, monkeypatch):
    monkeypatch.setattr(page_prep, "is_wall", lambda page, url: False)
    monkeypatch.setattr(page_prep, "is_auth_wall", lambda page: False)
    cp._provide_attempt(FakePage(), "password", "login.ibm.com")
    assert stubs == ["_ibm_login"]


def test_other_sites_never_run_site_steps(stubs, monkeypatch):
    monkeypatch.setattr(page_prep, "is_wall", lambda page, url: True)
    page = FakePage()
    page.url = "https://jobs.example.com/login"
    monkeypatch.setattr(cp, "_is_ibm_page", lambda p: False)
    assert cp._site_steps_cleared(page, "jobs.example.com", {}, False, None) is False
    assert stubs == []


def test_an_email_only_login_step_still_counts_as_the_wall(stubs, monkeypatch):
    """IBM's IBMid screen has no password box: is_wall says no, the engine's classify_entry says auth wall."""
    monkeypatch.setattr(page_prep, "is_wall", lambda page, url: False)
    monkeypatch.setattr(page_prep, "is_auth_wall", lambda page: True)
    cp._provide_attempt(FakePage(), "password", "login.ibm.com")
    assert stubs == ["_ibm_login", "generic_fill"]
