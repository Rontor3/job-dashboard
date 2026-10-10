import pytest
from fastapi.testclient import TestClient

from job_dashboard import config, llm


@pytest.fixture
def cfg_db(tmp_path, monkeypatch):
    db = str(tmp_path / "jobs.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    for k in config.KEYS:
        monkeypatch.delenv(k, raising=False)
    for k in ("LLM_API_KEY", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    return db


def test_table_value_wins_over_env_and_env_is_the_fallback(cfg_db, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert config.get("LLM_MODEL") == "from-env"
    config.put("LLM_MODEL", "from-table")
    assert config.get("LLM_MODEL") == "from-table"


def test_unset_key_reads_none_and_unknown_key_is_rejected(cfg_db):
    assert config.get("LLM_TIMEOUT") is None
    with pytest.raises(KeyError):
        config.put("LLM_API_KEY", "sk-secret")          # secrets stay in .env


def test_clearing_a_value_falls_back_to_env(cfg_db, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-env")
    config.put("LLM_MODEL", "x")
    config.put("LLM_MODEL", "")
    assert config.get("LLM_MODEL") == "from-env"


def test_migrate_copies_dotenv_values_once_without_overwriting(cfg_db, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LLM_MODEL=env-model\nLLM_TIMEOUT=60\nLLM_API_KEY=sk-x\n")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")           # only in the shell: not .env, so not copied
    config.put("LLM_TIMEOUT", "90")
    assert config.migrate_from_env(env) == ["LLM_MODEL"]
    monkeypatch.delenv("LLM_REASONING_EFFORT")
    assert config.get("LLM_MODEL") == "env-model" and config.get("LLM_TIMEOUT") == "90"
    assert config.get("LLM_REASONING_EFFORT") is None


def test_llm_client_picks_up_a_change_without_a_restart(cfg_db):
    calls = []

    def post(url, body):
        calls.append((url, body["model"]))
        return {"output_text": "ok"}

    llm.complete("hi", post=post)
    config.put("LLM_BASE_URL", "https://vllm.example/v1")
    config.put("LLM_MODEL", "qwen-next")
    llm.complete("hi", post=post)
    assert calls == [("http://localhost:11434/v1/responses", "qwen3:14b"),
                     ("https://vllm.example/v1/responses", "qwen-next")]


def test_config_api_lists_sets_and_says_when_a_restart_is_needed(cfg_db, tmp_path):
    from job_dashboard.api.app import create_app
    c = TestClient(create_app(db_path=str(tmp_path / "app.db")))
    keys = {row["key"]: row for row in c.get("/api/config").json()["config"]}
    assert set(keys) == set(config.KEYS) and keys["LLM_MODEL"]["value"] is None
    r = c.put("/api/config/LLM_MODEL", json={"value": "m2"}).json()
    assert r == {"key": "LLM_MODEL", "value": "m2", "restart": None}
    r = c.put("/api/config/AGENT_CDP_PORT", json={"value": "9444"}).json()
    assert r["restart"] == "browser"
    assert c.put("/api/config/LLM_API_KEY", json={"value": "x"}).status_code == 404
    assert c.put("/api/config/LLM_TIMEOUT", json={"value": "soon"}).status_code == 422
