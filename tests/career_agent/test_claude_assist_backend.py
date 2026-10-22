"""Walk-path debug transport: the Claude CLI subprocess — all offline (stubbed subprocess)."""
import inspect

import career_agent.orchestrator.claude_assist as ca
from career_agent.orchestrator.claude_assist import _backend_call, with_claude_fallback

PROMPT = "Look at the screenshot.\nDead end: stuck"


def test_backend_call_argv_is_preserved(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["kw"] = args, kw

        class R: stdout, stderr = '{"action":"go_back"}', "warn line\nlimit line\n"
        return R()

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    out = _backend_call(PROMPT)
    assert out == '{"action":"go_back"}'
    assert seen["args"] == ["claude", "-p", PROMPT, "--model", "sonnet", "--allowedTools", "Read", "--max-turns", "4"]
    assert seen["kw"].get("timeout") == 120 and "cwd" in seen["kw"]
    assert ca._LAST_STDERR == "limit line"           # stderr tail set for the echo check


def test_the_llm_cost_line_names_the_backend(monkeypatch):
    before = ca._CALLS.get("claude-cli", 0)
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: type("R", (), {"stdout": "x", "stderr": ""})())
    _backend_call("p")
    assert ca._CALLS["claude-cli"] == before + 1


def test_fallback_and_assist_default_route_through_the_one_router(monkeypatch):
    assert inspect.signature(ca.ClaudeAssist.__init__).parameters["run"].default is ca._backend_call
    dead = lambda prompt: (_ for _ in ()).throw(RuntimeError("ollama down"))
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: type("R", (), {"stdout": "cli draft", "stderr": ""})())
    assert with_claude_fallback(dead)("some prompt") == "cli draft"


def test_the_walk_debug_line_names_backend_model_action(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ca.subprocess, "run",
                        lambda args, **k: type("R", (), {"stdout": '{"action":"go_back"}', "stderr": ""})())
    a = ca.ClaudeAssist(cap=1, shot_dir=str(tmp_path))

    class P:
        url, frames = "https://x.example/job", []
        def screenshot(self, path): open(path, "wb").write(b"x")
        def go_back(self): pass
        def wait_for_timeout(self, ms): pass
    assert a.recover(P(), "stuck") is True
    assert "[walk-debug] claude-cli claude-sonnet → go_back" in capsys.readouterr().out
