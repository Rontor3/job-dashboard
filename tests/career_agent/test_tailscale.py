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


def test_falls_back_to_interface_ip_when_cli_absent(monkeypatch):
    # the real bug: no TAILSCALE_HOST, no `tailscale` CLI, but the tailnet IP is
    # on the interface -> read it from ifconfig instead of returning None.
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    IFCONFIG = "utun3: flags=8051\n\tinet 100.83.251.23 --> 100.83.251.23 netmask 0xffffffff\n"
    def runner(args, **k):
        if args[0] == "tailscale":
            raise FileNotFoundError()
        return type("R", (), {"returncode": 0, "stdout": IFCONFIG})()
    assert detect_host(load_settings(), runner=runner) == "100.83.251.23"


def test_none_when_no_tailnet_anywhere(monkeypatch):
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    def runner(args, **k):
        if args[0] == "tailscale":
            raise FileNotFoundError()
        return type("R", (), {"returncode": 0, "stdout": "en0:\n\tinet 192.168.1.5\n"})()
    assert detect_host(load_settings(), runner=runner) is None
