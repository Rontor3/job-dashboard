import ast
import inspect
import json

import pytest


def test_browser_deps_accepts_every_call_the_step_engine_makes():
    from career_agent.orchestrator import step_engine
    from career_agent.orchestrator.browser_deps import BrowserDeps
    calls = [(n.func.attr, len(n.args)) for n in ast.walk(ast.parse(inspect.getsource(step_engine)))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "deps"]
    assert calls
    for op, nargs in calls:
        inspect.signature(getattr(BrowserDeps, op)).bind(object(), *([None] * nargs))


def test_a_run_that_crashes_still_writes_its_result_json(tmp_path, monkeypatch):
    import career_agent.apply as a
    out = tmp_path / "result.json"
    monkeypatch.setattr("sys.argv", ["apply", "--url", "https://jobs.x/1", "--result-json", str(out)])

    def crash(args, box): raise RuntimeError("browser died")
    monkeypatch.setattr(a, "_apply", crash)
    with pytest.raises(RuntimeError):
        a.main()
    got = json.loads(out.read_text())
    assert got["url"] == "https://jobs.x/1" and got["stopped_reason"] == "error" and got["submitted"] is False
