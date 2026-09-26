from career_agent.config.settings import load_settings


def test_phase2_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("REMOTE_SOLVE_TTL", "120")
    monkeypatch.setenv("REMOTE_SOLVE_ALLOW_PUBLIC", "1")
    s = load_settings()
    assert s.telegram_bot_token == "123:abc"
    assert s.remote_solve_ttl == 120
    assert s.remote_solve_allow_public is True
