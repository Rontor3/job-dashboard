from job_dashboard import agent_browser, paths

_ensure_window = agent_browser.ensure_window      # conftest stubs it for every other test


def test_already_running_launches_nothing():
    launched = []
    windows = []
    assert agent_browser.ensure_running("http://127.0.0.1:9333", popen=lambda *a, **k: launched.append(a),
                                        is_up=lambda url: True, window=windows.append) is None
    assert launched == []
    assert windows == ["http://127.0.0.1:9333"]       # a windowless Chrome gets a tab before anyone attaches


def test_launches_with_its_own_profile_inside_the_data_root(monkeypatch):
    monkeypatch.setattr(agent_browser, "_executable", lambda: "/bin/chrome")
    monkeypatch.setattr(paths, "BROWSER_PROFILE", paths.TMP / "test-profile")
    ups = iter([False, True])
    launched = []
    assert agent_browser.ensure_running("http://127.0.0.1:9444", popen=lambda argv, **k: launched.append(argv),
                                        is_up=lambda url: next(ups)) is None
    argv = launched[0]
    assert argv[0] == "/bin/chrome"
    assert "--remote-debugging-port=9444" in argv
    assert f"--user-data-dir={paths.TMP / 'test-profile'}" in argv


def test_never_launches_for_a_remote_cdp_url():
    launched = []
    problem = agent_browser.ensure_running("http://10.0.0.5:9222", popen=lambda *a, **k: launched.append(a),
                                           is_up=lambda url: False)
    assert problem and "remote" in problem
    assert launched == []


def test_reports_when_it_never_comes_up(monkeypatch):
    monkeypatch.setattr(agent_browser, "_executable", lambda: "/bin/chrome")
    monkeypatch.setattr(paths, "BROWSER_PROFILE", paths.TMP / "test-profile")
    problem = agent_browser.ensure_running("http://127.0.0.1:9444", wait_s=0, popen=lambda *a, **k: None,
                                           is_up=lambda url: False)
    assert problem and "didn't answer" in problem


def test_off_switch_falls_back_to_default_port(monkeypatch):
    monkeypatch.setenv("CAREER_AGENT_CDP_URL", "off")
    monkeypatch.setenv("AGENT_CDP_PORT", "9555")
    assert agent_browser.cdp_url() == "http://127.0.0.1:9555"


def test_a_windowless_chrome_gets_a_blank_tab(monkeypatch):
    opened = []
    monkeypatch.setattr(agent_browser, "_page_count", lambda url: 0)
    monkeypatch.setattr(agent_browser.urllib.request, "urlopen",
                        lambda req, timeout=0: opened.append((req.get_method(), req.full_url)) or type("R", (), {"close": lambda s: None})())
    _ensure_window("http://127.0.0.1:9333")
    assert opened == [("PUT", "http://127.0.0.1:9333/json/new?about:blank")]


def test_a_chrome_with_a_window_is_left_alone(monkeypatch):
    monkeypatch.setattr(agent_browser, "_page_count", lambda url: 2)
    monkeypatch.setattr(agent_browser.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no tab opened")))
    _ensure_window("http://127.0.0.1:9333")
