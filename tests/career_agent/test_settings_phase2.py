from career_agent.config.settings import load_settings


def test_phase2_defaults(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "REMOTE_SOLVE_PORT",
              "REMOTE_SOLVE_TTL", "REMOTE_SOLVE_ALLOW_PUBLIC", "TAILSCALE_HOST"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.telegram_bot_token is None
    assert s.remote_solve_port == 8765
    assert s.remote_solve_ttl == 300
    assert s.remote_solve_allow_public is False


def test_phase2_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("REMOTE_SOLVE_TTL", "120")
    monkeypatch.setenv("REMOTE_SOLVE_ALLOW_PUBLIC", "1")
    s = load_settings()
    assert s.telegram_bot_token == "123:abc"
    assert s.remote_solve_ttl == 120
    assert s.remote_solve_allow_public is True
