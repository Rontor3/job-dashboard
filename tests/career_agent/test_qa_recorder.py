from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import qa_store
from job_dashboard.db import init_db


def _rec(tmp_path):
    return QARecorder(init_db(str(tmp_path / "t.db")), job_id=1)


def test_records_decisions_skips_uploads_and_tracks_open_then_answered(tmp_path):
    r = _rec(tmp_path)
    f = Field("#q", "text", "Why us?", True, [], None, None)
    r.decision(FillDecision("#n", "text", "Notice period?", "30 days", "fill", "recall"))
    r.decision(FillDecision("#cv", "file", "Resume", "/x.pdf", "upload", "resume"))   # not a question
    r.on_draft(f, {"answer": "guess", "confidence": 20, "basis": "none", "prompt": "P",
                   "unsupported_company_claims": ["Series B"]}, filled=False)
    r.needs(f)                                   # fill_node also flags it; must not wipe the draft
    n = r.conn.execute("select count(*) from application_qa").fetchone()[0]
    assert n == 2
    (q,) = qa_store.open_questions(r.conn, 1)
    assert (q["answer"], q["confidence"], q["context_json"]) == ("guess", 20, {"prompt": "P"})
    assert q["unsupported_claims"] == ["Series B"]
    r.answered(f, "Because fraud ML")            # Telegram reply mid-run closes it
    assert qa_store.open_questions(r.conn, 1) == []


def test_record_failure_never_raises(tmp_path):
    r = _rec(tmp_path)
    r.conn.close()
    r.needs(Field("#q", "text", "Q", True, [], None, None))   # closed db -> logged, not raised


def test_trace_is_merged_into_decision_and_needs_rows_and_outcome_updates(tmp_path):
    r = _rec(tmp_path)
    hit = Field("#n", "text", "Notice period?", False, [], None, None)
    miss = Field("#w", "text", "Favourite colour", False, [], None, None)
    traces = {"#n": {"retrieval_kind": "label_exact", "retrieved_qkey": "notice period",
                     "retrieval_score": 1.0, "candidates_json": [{"tier": "learned", "accepted": True}]},
              "#w": {"retrieval_kind": "none", "candidates_json": [{"tier": "learned", "score": 0.2, "accepted": False}]}}
    r.tracer = lambda f: traces[f.ref]
    r.trace_all([hit, miss])
    r.decision(FillDecision("#n", "text", "Notice period?", "30 days", "fill", "learned"))
    r.needs(miss)
    r.outcome("#n", "edited")
    rows = {x["ref"]: x for x in [dict(zip(["ref", "kind", "score", "cands", "outcome", "label"], row)) for row in
            r.conn.execute("select ref, retrieval_kind, retrieval_score, candidates_json, outcome, label from application_qa")]}
    assert rows["#n"]["kind"] == "label_exact" and rows["#n"]["score"] == 1.0
    assert rows["#n"]["outcome"] == "edited" and rows["#n"]["label"] == "Notice period?"
    assert rows["#w"]["kind"] == "none" and '"accepted": false' in rows["#w"]["cands"]


def test_trace_failure_is_swallowed(tmp_path):
    r = _rec(tmp_path)
    def boom(f): raise RuntimeError("x")
    r.tracer = boom
    r.trace_all([Field("#a", "text", "Q", False, [], None, None)])   # must not raise
