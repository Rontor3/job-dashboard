import pytest

from job_dashboard import llm
from job_dashboard.apply import local_model


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "OLLAMA_MODEL", "LLM_REASONING_EFFORT",
              "LLM_NO_TEMPERATURE", "LLM_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _capture():
    calls = []

    def post(url, body):
        calls.append((url, body))
        return {"output": [{"type": "reasoning", "summary": []},
                           {"type": "message", "content": [{"type": "output_text", "text": '```json\n{"a": 1}\n```'}]}]}
    return calls, post


def test_defaults_talk_to_local_ollama_responses_endpoint_without_thinking(clean_env):
    calls, post = _capture()
    assert llm.complete_json("hi", temperature=0.1, post=post) == {"a": 1}
    url, body = calls[0]
    assert url == "http://localhost:11434/v1/responses"
    assert body["model"] == "qwen3:14b" and body["input"] == "hi" and body["temperature"] == 0.1
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["reasoning"] == {"effort": "none"}


def test_swapping_provider_is_env_only(clean_env):
    clean_env.setenv("LLM_BASE_URL", "https://api.openai.com/v1/")
    clean_env.setenv("LLM_MODEL", "gpt-5-mini")
    clean_env.setenv("LLM_NO_TEMPERATURE", "1")
    calls, post = _capture()
    llm.complete("hi", temperature=0.4, post=post)
    url, body = calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert body["model"] == "gpt-5-mini"
    assert "temperature" not in body and "reasoning" not in body


def test_output_text_convenience_field_wins():
    assert llm.output_text({"output_text": "plain"}) == "plain"


def test_missing_text_raises_so_callers_fall_back():
    with pytest.raises(ValueError):
        llm.output_text({"output": [], "error": {"message": "model not found"}})


def test_parse_json_tolerates_prose_around_the_object():
    assert llm.parse_json('Sure! {"k": [1, 2]} hope that helps') == {"k": [1, 2]}


def test_local_model_never_starts_or_kills_ollama_for_a_remote_provider(clean_env):
    clean_env.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    assert local_model._ollama_root() is None
    assert local_model.is_up() is False
