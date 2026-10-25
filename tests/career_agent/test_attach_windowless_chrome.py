"""A Chrome with no windows refuses a CDP attach; the launcher opens one blank tab first (2026-10-25)."""
import io, json
from career_agent.browser import runner


def _fake(tabs, calls):
    def urlopen(req, timeout=None):
        url = getattr(req, "full_url", req)
        calls.append((getattr(req, "method", "GET") if not isinstance(req, str) else "GET", url))
        return io.BytesIO(json.dumps(tabs).encode())
    return urlopen


def test_opens_a_tab_when_chrome_has_none(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", _fake([], calls))
    runner._ensure_a_window("http://localhost:9222")
    assert ("PUT", "http://localhost:9222/json/new?about:blank") in calls


def test_leaves_chrome_alone_when_a_tab_exists(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", _fake([{"type": "page"}], calls))
    runner._ensure_a_window("http://localhost:9222")
    assert all(m == "GET" for m, _ in calls)
