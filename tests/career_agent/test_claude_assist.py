from career_agent.orchestrator.claude_assist import ClaudeAssist, parse_action, validate

CTRLS = [{"name": "Continue to role", "role": "button", "ref": "[data-aff=a1]", "frame": 0},
         {"name": "Submit application", "role": "button", "ref": "[data-aff=a2]", "frame": 0}]


def test_parse_action_finds_json_in_chatter():
    assert parse_action('Sure.\n{"action": "click", "index": 0, "why": "x"} done') == \
        {"action": "click", "index": 0, "why": "x"}
    assert parse_action("no json here") is None and parse_action("{bad") is None


def test_validate_whitelists_actions_and_controls():
    ok = validate({"action": "click", "index": 0}, CTRLS)
    assert ok["control"]["name"] == "Continue to role"
    assert validate({"action": "click", "index": 1}, CTRLS) is None          # submit is never assist-clickable
    assert validate({"action": "click", "index": 9}, CTRLS) is None          # not a listed control
    assert validate({"action": "type", "text": "x"}, CTRLS) is None          # unknown action
    assert validate({"action": "go_back"}, CTRLS) == {"action": "go_back"}


class _Page:
    url = "https://site.example/job"
    frames = []

    def __init__(self): self.went_back = 0
    def screenshot(self, path): open(path, "wb").write(b"x")
    def go_back(self): self.went_back += 1
    def wait_for_timeout(self, ms): pass


def test_recover_is_capped_and_gives_up_cleanly(tmp_path):
    replies = iter(['{"action":"go_back"}'] * 10)
    a = ClaudeAssist(cap=2, run=lambda prompt: next(replies), shot_dir=str(tmp_path))
    p = _Page()
    assert a.recover(p, "stuck") and a.recover(p, "stuck")
    assert p.went_back == 2
    assert a.recover(p, "stuck") is False                                    # cap reached -> engine gives up as before


def test_recover_survives_claude_failure(tmp_path):
    def boom(prompt): raise TimeoutError("claude hung")
    assert ClaudeAssist(cap=5, run=boom, shot_dir=str(tmp_path)).recover(_Page(), "stuck") is False
    assert ClaudeAssist(cap=5, run=lambda p: "garbage", shot_dir=str(tmp_path)).recover(_Page(), "stuck") is False


def test_the_screenshot_dir_is_absolute_so_claude_p_can_read_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = ClaudeAssist(cap=1, run=lambda p: '{"action":"give_up"}', shot_dir="rel/agent_runs/9")
    assert a._dir.is_absolute() and a._dir.exists() and a._dir == (tmp_path / "rel/agent_runs/9").resolve()
    seen = []
    a._run = lambda prompt: seen.append(prompt) or '{"action":"give_up"}'

    class P:
        url, frames = "https://x.example/job", []
        def screenshot(self, path): open(path, "wb").write(b"x")
        def wait_for_timeout(self, ms): pass
    a.recover(P(), "stuck")
    assert str(a._dir / "assist1.png") in seen[0]            # the path handed to Claude is the absolute one
