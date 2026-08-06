import json
import pytest
from job_dashboard.linkedin.voyager import (
    VoyagerClient, LinkedInAuthError,
)


def fake_fetch(responses):
    """responses: list of (status, body); returns a fetch() recording calls."""
    calls = []
    def _fetch(url, headers):
        calls.append((url, headers))
        status, body = responses.pop(0)
        return status, body
    _fetch.calls = calls
    return _fetch


def test_csrf_token_is_jsessionid_without_quotes():
    c = VoyagerClient("LIAT", 'ajax:99', fetch=lambda u, h: (200, "{}"))
    assert c.headers["csrf-token"] == "ajax:99"
    assert 'JSESSIONID="ajax:99"' in c.headers["Cookie"]
    assert "li_at=LIAT" in c.headers["Cookie"]


def test_me_returns_json_on_200():
    body = json.dumps({"included": [{"firstName": "Rakshit", "lastName": "Singh"}]})
    c = VoyagerClient("x", "ajax:1", fetch=fake_fetch([(200, body)]))
    assert c.me()["included"][0]["firstName"] == "Rakshit"


def test_me_raises_auth_error_on_302():
    c = VoyagerClient("x", "ajax:1", fetch=fake_fetch([(302, "")]))
    with pytest.raises(LinkedInAuthError):
        c.me()
