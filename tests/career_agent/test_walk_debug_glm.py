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
    monkeypatch.delenv("CAREER_OCE_MODEL", raising=False)      # opencode outranks glm
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
    monkeypatch.delenv("CAREER_OCE_MODEL", raising=False)
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
    monkeypatch.delenv("CAREER_OCE_MODEL", raising=False)
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

    monkeypatch.delenv("CAREER_OCE_MODEL", raising=False)
    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: type("R", (), {"stdout": "cli draft", "stderr": ""})())
    assert with_claude_fallback(dead)("some prompt") == "cli draft"      # argv path, unchanged behavior

    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (req.full_url.endswith("/chat/completions"), _Resp())[1])
    assert with_claude_fallback(dead)("some prompt") == '{"action":"go_back"}'   # text-only GLM draft


# ---------------------------------------------------------------- the OpenCode desktop backend

ASSISTANT = {"id": "msg_new", "type": "assistant", "finish": "stop",
             "content": [{"type": "reasoning", "text": "thinking not part of the answer"},
                         {"type": "text", "text": '{"action":"go_back"}'}]}
PRE = [{"id": "msg_old", "type": "synthetic"}, {"id": "msg_older_assistant", "type": "assistant",
                                                "finish": "stop", "content": [{"type": "text", "text": "stale"}]}]
TURN = PRE + [{"id": "msg_user", "type": "user", "text": PROMPT}, ASSISTANT]


def oce_fake(timeline):
    """A scripted run_cli: `timeline` lists the message-list snapshots served per GET poll."""
    st = {"session_posts": 0, "polls": 0, "prompt_paths": [], "prompt_bodies": [], "interrupted": False}

    def run(args, input=None, timeout=None):
        cmd, path = args[0], args[1]
        data = json.loads(args[args.index("--data") + 1]) if "--data" in args else None
        if path == "/api/session":
            st["session_posts"] += 1
            return 0, json.dumps({"data": {"id": "ses_t", "title": "career-agent walk debug"}}), ""
        if cmd == "post" and "/prompt" in path:
            st["prompt_paths"].append(path)
            st["prompt_bodies"].append(data)
            return 0, json.dumps({"data": {"id": "msg_user", "type": "user"}}), ""
        if cmd == "get" and path.endswith("/message"):
            snap = timeline[min(st["polls"], len(timeline) - 1)]
            st["polls"] += 1
            return 0, json.dumps({"data": snap, "cursor": {"previous": None, "next": None}}), ""
        if cmd == "post" and path.endswith("/interrupt"):
            st["interrupted"] = True
            return 0, '{"interrupted":false}', ""
        return 1, "", f"unexpected call: {args}"

    return run, st


def oce_env(monkeypatch):
    monkeypatch.setenv("CAREER_OCE_MODEL", "glm-5.3-flash-free")
    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    monkeypatch.setattr(ca, "_OCE_SESSION", None)
    monkeypatch.setattr(ca, "_SLEEP", lambda *_: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(
        AssertionError("opencode must not touch urllib")))
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("opencode must round-trip through run_cli, not subprocess.run")))


def test_precedence_opencode_then_glm_then_claude(monkeypatch):
    oce_env(monkeypatch)
    run, st = oce_fake([PRE, TURN])
    monkeypatch.setattr(ca, "run_cli", run)
    assert _backend_call(PROMPT) == '{"action":"go_back"}'
    assert ca._BACKEND == "opencode" and st["session_posts"] == 1
    assert st["prompt_paths"] == ["/api/session/ses_t/prompt"]   # built through run_cli: session then prompt

    class R: stdout, stderr = '{"action":"go_back"}', ""
    monkeypatch.delenv("CAREER_OCE_MODEL", raising=False)         # a present z.ai key never outranks opencode,
    monkeypatch.setenv("CAREER_GLM_API_KEY", "k")                # but once OCE is unset the glm branch wins
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    assert _backend_call(PROMPT) == '{"action":"go_back"}'
    assert ca._BACKEND == "glm"

    monkeypatch.delenv("CAREER_GLM_API_KEY", raising=False)
    monkeypatch.setattr(ca.subprocess, "run", lambda args, **k: R())
    assert _backend_call(PROMPT) == '{"action":"go_back"}'       # and the plain Claude CLI is last
    assert ca._BACKEND == "claude-cli"


def test_session_created_once_and_reused_across_calls(monkeypatch):
    oce_env(monkeypatch)
    run, st = oce_fake([PRE, TURN, PRE, TURN])
    monkeypatch.setattr(ca, "run_cli", run)
    n0 = ca._CALLS.get("opencode", 0)
    assert _backend_call(PROMPT) and _backend_call(PROMPT)
    assert st["session_posts"] == 1                                         # created once per process…
    assert st["prompt_paths"] == ["/api/session/ses_t/prompt"] * 2          # …and reused by both calls
    assert ca._CALLS["opencode"] == n0 + 2


def test_prompt_body_text_and_file_attachment(monkeypatch, tmp_path):
    oce_env(monkeypatch)
    png = tmp_path / "assist1.png"
    png.write_bytes(b"\x89PNG fake")
    run, st = oce_fake([PRE, TURN, PRE, TURN])          # two full calls: each turn = before-snapshot + reply poll
    monkeypatch.setattr(ca, "run_cli", run)
    _backend_call(PROMPT, image_path=str(png))
    body = st["prompt_bodies"][0]
    assert body["text"] == PROMPT                                          # the prompt bytes ride untouched
    att = body["files"][0]
    assert att["uri"].startswith("file://") and att["uri"].endswith("/assist1.png")   # server resolves the file itself
    assert att["name"] == "assist1.png"
    _backend_call(PROMPT)                                                  # no file -> text-only body
    assert st["prompt_bodies"][1] == {"text": PROMPT}


def test_reply_parsing_prefers_text_parts_of_the_newest_finished_turn(monkeypatch):
    oce_env(monkeypatch)
    wrapped = {"info": {"id": "msg_wr", "type": "assistant", "finish": "stop"},   # older {info,parts} shape …
               "parts": [{"type": "text", "text": "wrapped works too"}]}
    run, st = oce_fake([PRE, PRE + [{"id": "msg_u", "type": "user"}, wrapped, ASSISTANT]])
    monkeypatch.setattr(ca, "run_cli", run)
    text = _backend_call(PROMPT)
    assert text == '{"action":"go_back"}'                                  # reasoning + trailing noise dropped…
    assert "stale" not in text and "wrapped" not in text                   # …pre-turn assistant excluded


def test_streaming_turn_waits_until_finish_then_answers(monkeypatch):
    oce_env(monkeypatch)
    streaming = {"id": "msg_new", "type": "assistant", "finish": None, "content": []}
    run, st = oce_fake([PRE, PRE + [streaming], PRE + [streaming], TURN])   # two polls still streaming
    monkeypatch.setattr(ca, "run_cli", run)
    assert _backend_call(PROMPT) == '{"action":"go_back"}'
    assert st["polls"] >= 4


def test_timeout_interrupts_the_turn_and_raises(monkeypatch):
    oce_env(monkeypatch)
    run, st = oce_fake([PRE])                                              # user message never arrives
    monkeypatch.setattr(ca, "run_cli", run)
    t = iter(range(0, 100000, 1000))                                       # fake clock, one jump per read
    monkeypatch.setattr(ca, "_NOW", lambda: next(t))
    with pytest.raises(RuntimeError) as e:
        _backend_call(PROMPT, timeout=60)
    assert len(str(e.value)) <= 200 and "no reply within 60s" in str(e.value)
    assert st["interrupted"] is True                                       # best-effort interrupt fired
    assert ca._LAST_STDERR                                                 # echo slot armed despite the empty detail


def test_cli_failures_become_short_runtimeerrors_with_last_stderr(monkeypatch):
    oce_env(monkeypatch)
    monkeypatch.setattr(ca, "run_cli", lambda a, input=None, timeout=None: (1, "", "server unreachable"))
    with pytest.raises(RuntimeError) as e:
        _backend_call(PROMPT)
    assert len(str(e.value)) <= 200 and "session create" in str(e.value)
    assert ca._LAST_STDERR == "server unreachable"

    run, _ = oce_fake([PRE])
    monkeypatch.setattr(ca, "run_cli", run)
    def bad_prompt(args, input=None, timeout=None):
        if "/prompt" in args[1]:
            return 1, json.dumps({"_tag": "InvalidRequestError",
                                  "message": "Invalid attachment URI: /ghost.png"}), "HTTP 400"
        return run(args, input, timeout)
    monkeypatch.setattr(ca, "run_cli", bad_prompt)
    with pytest.raises(RuntimeError) as e:
        _backend_call(PROMPT, image_path="ghost.png")
    assert "Invalid attachment URI" in str(e.value)
    assert ca._LAST_STDERR == "Invalid attachment URI: /ghost.png"          # the echoed body line


def test_reply_finished_with_error_is_a_failure_not_a_draft(monkeypatch):
    oce_env(monkeypatch)
    errored = {"id": "msg_new", "type": "assistant", "finish": "error", "error": "rate limited", "content": []}
    run, _ = oce_fake([PRE, PRE + [errored]])
    monkeypatch.setattr(ca, "run_cli", run)
    with pytest.raises(RuntimeError) as e:
        _backend_call(PROMPT)
    assert "finished with error" in str(e.value)
    assert ca._LAST_STDERR == "rate limited"


def test_the_walk_debug_line_names_backend_model_action(monkeypatch, tmp_path, capsys):
    oce_env(monkeypatch)
    run, _ = oce_fake([PRE, TURN])
    monkeypatch.setattr(ca, "run_cli", run)
    a = ca.ClaudeAssist(cap=1, shot_dir=str(tmp_path))                     # real router -> real opencode branch

    class P:
        url, frames = "https://x.example/job", []
        def screenshot(self, path): open(path, "wb").write(b"x")
        def go_back(self): pass
        def wait_for_timeout(self, ms): pass
    assert a.recover(P(), "stuck") is True
    out = capsys.readouterr().out
    assert "[walk-debug] opencode glm-5.3-flash-free → go_back" in out
