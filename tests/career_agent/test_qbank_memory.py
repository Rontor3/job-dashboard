from job_dashboard import qa_store
from job_dashboard.db import init_db

from career_agent.memory.qbank_memory import QBankMemory
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder


def test_recall_splits_confident_likely_none(qbank_conn, fake_embed, make_field):
    mem = QBankMemory(qbank_conn, embed=fake_embed, job={"location": "Noida"})
    fields = [make_field("Notice period", ref="#n"), make_field("LinkedIn profile URL", ref="#l"),
              make_field("Describe your favourite hobby outside work", ref="#h")]
    ex = mem.explain(fields[0])
    assert (ex["retrieval_kind"], ex["retrieved_qkey"], ex["confidence"]) == ("exact", "notice_period", 100)
    assert ex["candidates_json"][0] == {"tier": "qbank", "qkey": "notice_period", "score": 1.0, "accepted": True}
    decisions, still = mem.recall(fields)
    assert [(d.ref, d.value, d.source, d.action) for d in decisions] == [
        ("#n", "30", "qbank", "fill"), ("#l", "linkedin.com/in/x", "qbank_likely", "fill")]
    assert [f.ref for f in still] == ["#h"]
    assert mem.explain(fields[2])["retrieved_qkey"] is None
    assert mem.record(fields[0], "x") is None and mem.record_corrections([], [], {}) is None


def test_likely_fill_is_recorded_for_review(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    rec = QARecorder(conn, 1, run_key="r")
    rec.decision(FillDecision("#a", "text", "LinkedIn profile URL", "x", "fill", "qbank_likely"))
    rec.decision(FillDecision("#b", "text", "Notice period", "30", "fill", "qbank"))
    assert dict(conn.execute("select ref, status from application_qa")) == {"#a": "needs_answer", "#b": "filled"}
    (q,) = qa_store.open_questions(conn, 1)
    assert (q["label"], q["answer"], q["source"]) == ("LinkedIn profile URL", "x", "qbank_likely")


def test_qbank_setting_default_and_clamp(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    default = qa_store.qbank_confident_min(conn)
    assert 0 < default <= 100
    qa_store.set_setting(conn, "qbank_confident_min", 150)
    assert qa_store.qbank_confident_min(conn) == 100


def test_recall_survives_answer_field_blowup(qbank_conn, fake_embed, make_field, monkeypatch):
    mem = QBankMemory(qbank_conn, embed=fake_embed, job={"location": "Noida"})
    import career_agent.memory.qbank_memory as qm
    monkeypatch.setattr(qm, "answer_field", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    f = make_field("Notice period", ref="#n")
    decisions, still = mem.recall([f])
    assert decisions == [] and [x.ref for x in still] == ["#n"]
    assert mem.explain(f)["retrieval_kind"] == "none"
