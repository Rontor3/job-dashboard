from job_dashboard import agent_browser, start


def test_cold_start_launches_the_agent_browser_on_the_dashboard(monkeypatch):
    launched = []
    monkeypatch.setattr(agent_browser, "ensure_running", lambda **k: launched.append(k["start_url"]))
    monkeypatch.setattr(agent_browser, "show_tab", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no extra tab")))
    assert start.show_dashboard("http://localhost:8000", server_up=lambda u: True) is None
    assert launched == ["http://localhost:8000"]


def test_running_browser_gets_the_dashboard_as_a_tab(monkeypatch):
    shown = []
    monkeypatch.setattr(agent_browser, "reachable", lambda *a, **k: True)
    monkeypatch.setattr(agent_browser, "show_tab", lambda url: shown.append(url) or True)
    assert start.show_dashboard("http://localhost:8000", server_up=lambda u: True) is None
    assert shown == ["http://localhost:8000"]


def test_gives_up_when_the_server_never_answers(monkeypatch):
    monkeypatch.setattr(agent_browser, "ensure_running", lambda **k: (_ for _ in ()).throw(AssertionError("no launch")))
    problem = start.show_dashboard("http://localhost:8000", wait_s=0, server_up=lambda u: False, sleep=lambda s: None)
    assert "didn't answer" in problem
