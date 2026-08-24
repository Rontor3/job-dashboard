from career_agent.integrations.live_view.tailscale import detect_host
from career_agent.config.settings import load_settings


def test_prefers_explicit_setting(monkeypatch):
    monkeypatch.setenv("TAILSCALE_HOST", "mac.ts.net")
    assert detect_host(load_settings()) == "mac.ts.net"


def test_parses_cli_when_unset(monkeypatch):
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    class R: returncode = 0; stdout = "100.101.102.103\n"
    assert detect_host(load_settings(), runner=lambda *a, **k: R()) == "100.101.102.103"


def test_none_when_cli_missing(monkeypatch):
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    def boom(*a, **k): raise FileNotFoundError()
    assert detect_host(load_settings(), runner=boom) is None
