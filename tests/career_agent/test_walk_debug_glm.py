"""Walk-path debug transport: GLM 5.3 Flash over HTTP when CAREER_GLM_API_KEY is set,
else the Claude CLI subprocess exactly as before — all offline (stubbed urlopen/subprocess)."""
import base64
import inspect
import io
import json
import urllib.error
import urllib.request

import pytest

import career_agent.orchestrator.claude_assist as ca
from career_agent.orchestrator.claude_assist import _backend_call, with_claude_fallback

PROMPT = "Look at the screenshot.\nDead end: stuck"


class _Resp:
    def __init__(self, payload=b'{"choices":[{"message":{"content":"{\\"action\\":\\"go_back\\"}"}}]}'):
        self._b = payload if isinstance(payload, bytes) else payload.encode()

    def read(self): return self._b

    def __enter__(self): return self

    def __exit__(self, *a): return False


def test_router_picks_glm_when_key_set(monkeypatch):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k-test")
    cap = {}

    def fake_urlopen(req, timeout=None):
        cap["url"], cap["timeout"], cap["req"] = req.full_url, timeout, req
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _backend_call(PROMPT, timeout=9) == '{"action":"go_back"}'
    assert cap["url"].endswith("/chat/completions") and cap["timeout"] == 9   # timeout passed through
    body = json.loads(cap["req"].data)
    assert body == {"model": "glm-5.3-flash", "temperature": 0, "max_tokens": 512,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}]}
    assert cap["req"].get_header("Authorization") == "Bearer k-test"
    assert ca._LAST_STDERR == ""                                              # a clean call clears the echo slot


def test_router_picks_cli_when_key_unset_and_argv_is_preserved(monkeypatch):
    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["kw"] = args, kw

        class R: stdout, stderr = '{"action":"go_back"}', "warn line\nlimit line\n"
        return R()

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    out = _backend_call(PROMPT)
    assert out == '{"action":"go_back"}'
    assert seen["args"] == ["claude", "-p", PROMPT, "--allowedTools", "Read", "--max-turns", "4"]
    assert seen["args"][2] == PROMPT                 # the prompt bytes passed to the CLI are exactly ours
    assert seen["kw"].get("timeout") == 120 and "cwd" in seen["kw"]
    assert ca._LAST_STDERR == "limit line"           # stderr tail set for the echo check, as before


def test_image_file_becomes_a_data_url_part(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    png = tmp_path / "assist1.png"
    png.write_bytes(b"\x89PNG-fake-bytes")
    cap = {}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (cap.update(req=req), _Resp())[1])

    _backend_call(PROMPT, image_path=str(png))
    parts = json.loads(cap["req"].data)["messages"][0]["content"]
    assert len(parts) == 2 and parts[0] == {"type": "text", "text": PROMPT}
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == png.read_bytes()


def test_missing_or_none_image_is_text_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    prose = {}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (prose.update(req=req), _Resp())[1])

    _backend_call(PROMPT, image_path=None)
    _backend_call(PROMPT, image_path=str(tmp_path / "ghost.png"))   # path that does not exist
    for req in prose.values():
        parts = json.loads(req.data)["messages"][0]["content"]
        assert parts == [{"type": "text", "text": PROMPT}]


def test_http_error_sets_last_stderr_and_raises_a_short_reason(monkeypatch):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    body = b'{"error":{"msg":"You\'ve hit your weekly limit"}}\n\nResets Oct 22 at 5:30am'
    err = urllib.error.HTTPError("https://api.z.ai/chat/completions", 429, "Too Many", {}, io.BytesIO(body))

    def refusing(req, timeout=None):
        raise err

    monkeypatch.setattr(urllib.request, "urlopen", refusing)
    with pytest.raises(RuntimeError) as e:
        _backend_call(PROMPT)
    assert len(str(e.value)) <= 200 and "429" in str(e.value)
    assert ca._LAST_STDERR == "Resets Oct 22 at 5:30am"    # the body's last line, so error_shaped's echo works


def test_unreadable_reply_shape_counts_as_a_failure(monkeypatch):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp(payload=b"{}"))
    with pytest.raises(RuntimeError):
        _backend_call(PROMPT)
    assert ca._LAST_STDERR


def test_base_url_and_model_env_are_honored(monkeypatch):
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    monkeypatch.setenv("CAREER_GLM_BASE_URL", "https://glm.test/paas/")
    monkeypatch.setenv("CAREER_GLM_MODEL", "glm-x")
    cap = {}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (cap.update(req=req), _Resp())[1])

    _backend_call("p")
    assert cap["req"].full_url == "https://glm.test/paas/chat/completions"
    assert json.loads(cap["req"].data)["model"] == "glm-x"


def test_the_llm_cost_line_names_the_backend(monkeypatch):
    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    before = ca._CALLS.get("claude-cli", 0)
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: type("R", (), {"stdout": "x", "stderr": ""})())
    _backend_call("p")
    assert ca._CALLS["claude-cli"] == before + 1

    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    gbefore = ca._CALLS.get("glm", 0)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    _backend_call("p")
    assert ca._CALLS["glm"] == gbefore + 1


def test_fallback_and_assist_default_route_through_the_one_router(monkeypatch):
    assert inspect.signature(ca.ClaudeAssist.__init__).parameters["run"].default is ca._backend_call
    dead = lambda prompt: (_ for _ in ()).throw(RuntimeError("ollama down"))

    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: type("R", (), {"stdout": "cli draft", "stderr": ""})())
    assert with_claude_fallback(dead)("some prompt") == "cli draft"      # argv path, unchanged behavior

    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (req.full_url.endswith("/chat/completions"), _Resp())[1])
    assert with_claude_fallback(dead)("some prompt") == '{"action":"go_back"}'   # text-only GLM draft
