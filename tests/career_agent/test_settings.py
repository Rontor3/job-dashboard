from career_agent.config import settings
from career_agent.config.settings import load_settings
from job_dashboard import paths


def test_defaults_point_inside_the_data_root(monkeypatch):
    monkeypatch.setattr(settings, "_load_dotenv", lambda: None)
    for k in ("CAREER_AGENT_USER_DATA_DIR", "CAREER_AGENT_HEADED", "CAREER_AGENT_CDP_URL", "AGENT_CDP_PORT"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.user_data_dir.startswith(str(paths.DATA_DIR))
    assert s.headed is True
    assert s.cdp_url == "http://127.0.0.1:9333"


def test_env_overrides(monkeypatch):
    monkeypatch.setattr(settings, "_load_dotenv", lambda: None)
    monkeypatch.setenv("CAREER_AGENT_HEADED", "0")
    monkeypatch.setenv("CAREER_AGENT_CDP_URL", "off")
    s = load_settings()
    assert s.headed is False
    assert s.cdp_url is None
