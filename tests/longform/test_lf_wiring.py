from types import SimpleNamespace as NS

from career_agent.orchestrator import judgment
from career_agent.orchestrator.judgment import JudgmentContext, judge


def field(label="Why do you want to join us?"):
    return NS(ref="r1", kind="textarea", label=label, purpose=None, required=True, options=[], description="")


def test_the_longform_hook_answers_prose_fields_instead_of_the_old_drafter(monkeypatch):
    def old_drafter(*a, **k): raise AssertionError("the old drafter must not run")
    monkeypatch.setattr(judgment, "draft_screening_answer", old_drafter)
    res = {"answer": "From longform.", "confidence": 90, "flags": [], "unsupported_company_claims": [], "basis": "b",
           "prompt": "p", "needs": ["why_company"], "project_id": "p-graph", "used": ["story:x"]}
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"}, longform=lambda q, f, j=None: res)
    seen = []
    answered, still, _ = judge([field()], ctx, llm=lambda p: "", on_draft=lambda f, r, filled: seen.append(r))
    assert [d.value for d in answered] == ["From longform."] and still == []
    assert seen[0]["project_id"] == "p-graph"


def test_a_failing_or_empty_hook_falls_back_to_the_old_drafter(monkeypatch):
    calls = []
    monkeypatch.setattr(judgment, "draft_screening_answer",
                        lambda *a, **k: calls.append(1) or {"answer": "Old.", "confidence": 80, "flags": [],
                                                           "unsupported_company_claims": []})

    def boom(q, f, j=None): raise RuntimeError("longform broke")
    for hook in (boom, lambda q, f, j=None: None):
        ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"}, longform=hook)
        answered, _, _ = judge([field()], ctx, llm=lambda p: "")
        assert [d.value for d in answered] == ["Old."]
    assert len(calls) == 2


def test_without_a_hook_nothing_changes(monkeypatch):
    monkeypatch.setattr(judgment, "draft_screening_answer",
                        lambda *a, **k: {"answer": "Old.", "confidence": 80, "flags": [], "unsupported_company_claims": []})
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"})
    assert [d.value for d in judge([field()], ctx, llm=lambda p: "")[0]] == ["Old."]


def test_the_recorder_keeps_how_the_draft_was_built():
    from career_agent.orchestrator.qa_recorder import QARecorder
    rec = QARecorder.__new__(QARecorder)
    captured = {}
    rec._rec = lambda ref, label, **kw: captured.update(kw)
    rec.on_draft(field(), {"answer": "A", "confidence": 90, "basis": "b", "prompt": "P", "needs": ["intro"],
                           "project_id": "p-ocr", "used": ["card:p-ocr"], "unsupported_company_claims": []}, True)
    assert captured["context_json"] == {"prompt": "P", "needs": ["intro"], "project_id": "p-ocr", "used": ["card:p-ocr"]}


def test_make_longform_or_none_returns_none_when_ingredients_missing(tmp_path, capsys):
    """make_longform_or_none returns None (not raising) when ingredients.json does not exist."""
    import sqlite3
    from pathlib import Path
    from career_agent.longform.pipeline import make_longform_or_none
    from career_agent.memory.qbank import ensure

    conn = sqlite3.connect(":memory:")
    ensure(conn)
    result = make_longform_or_none(conn, {"id": 1, "title": "t", "company": "c"}, {},
                                   lambda p: "", None, tmp_path / "missing.json")
    assert result is None
    out, _ = capsys.readouterr()
    assert "longform unavailable" in out


def test_make_longform_or_none_returns_callable_with_real_ingredients():
    """make_longform_or_none returns a callable when ingredients.json exists."""
    import sqlite3
    from pathlib import Path
    from career_agent.longform.pipeline import make_longform_or_none
    from career_agent.memory.qbank import ensure

    conn = sqlite3.connect(":memory:")
    ensure(conn)
    fixtures_path = Path(__file__).parent / "fixtures" / "ingredients.json"
    result = make_longform_or_none(conn, {"id": 1, "title": "t", "company": "c"}, {},
                                   lambda p: "", None, fixtures_path)
    assert result is not None
    assert callable(result)


def test_the_hook_receives_the_current_job(monkeypatch):
    got = []
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"},
                          longform=lambda q, f, j=None: got.append(j) or {"answer": "A", "confidence": 90, "flags": []})
    ctx.job = {"title": "page", "description": "scraped"}                  # apply.py swaps the job after the page loads
    judge([field()], ctx, llm=lambda p: "")
    assert got == [ctx.job]


def test_the_recorder_stores_flags_only_when_present():
    from career_agent.orchestrator.qa_recorder import QARecorder
    rec = QARecorder.__new__(QARecorder)
    captured = {}
    rec._rec = lambda ref, label, **kw: captured.update(kw)
    rec.on_draft(field(), {"answer": "A", "flags": ["project_leak:p-churn"]}, False)
    assert captured["context_json"]["flags"] == ["project_leak:p-churn"]
    rec.on_draft(field(), {"answer": "A", "flags": []}, True)
    assert "flags" not in captured["context_json"]


def test_the_recorder_stores_plan_provenance_only_when_present():
    from career_agent.orchestrator.qa_recorder import QARecorder
    rec = QARecorder.__new__(QARecorder)
    captured = {}
    rec._rec = lambda ref, label, **kw: captured.update(kw)
    rec.on_draft(field(), {"answer": "A", "plan_source": "llm", "plan_reason": "asks about goals"}, True)
    assert captured["context_json"]["plan_source"] == "llm"
    assert captured["context_json"]["plan_reason"] == "asks about goals"
    rec.on_draft(field(), {"answer": "A", "plan_source": "", "plan_reason": ""}, True)
    assert "plan_source" not in captured["context_json"] and "plan_reason" not in captured["context_json"]
