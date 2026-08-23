import os
from career_agent.config.settings import load_settings, Settings


def test_defaults_when_env_absent(monkeypatch):
    for k in ("CAREER_AGENT_USER_DATA_DIR", "CAREER_AGENT_HEADED",
              "OLLAMA_HOST", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.user_data_dir.endswith("career_agent/chrome-profile")
    assert s.headed is True
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_model == "qwen3:14b"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CAREER_AGENT_HEADED", "0")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:30b-a3b")
    s = load_settings()
    assert s.headed is False
    assert s.ollama_model == "qwen3:30b-a3b"
