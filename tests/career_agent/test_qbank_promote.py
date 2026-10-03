from career_agent.browser.form_model import Field
from career_agent.memory import qbank
from career_agent.memory.qbank_promote import promote_answer
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import qa_store
from job_dashboard.db import init_db


def _conn(tmp_path, fake_embed):
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn)
    qbank.ensure(conn)
    return conn


def _f(label, kind="text", ref="#a"):
    return Field(ref, kind, label, True, [], None, None)


def _answers(conn):
    return {e["question"]: e["answer"] for e in qbank.entries(conn)}


def test_a_new_question_answered_by_the_human_joins_the_answers(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    eid = promote_answer(conn, _f("Do you have experience with Kubernetes in production?"), "Yes, 2 years", fake_embed)
    assert eid and _answers(conn)["Do you have experience with Kubernetes in production?"] == "Yes, 2 years"
    assert qbank.exact(conn, "Do you have experience with Kubernetes in production?") == eid     # next time: exact hit


def test_the_type_x_instruction_is_dropped_from_the_saved_question(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    promote_answer(conn, _f('Where is your current location? If relocating, type "relocating".'), "Pune", fake_embed)
    assert "Where is your current location?" in _answers(conn)


def test_an_existing_unanswered_entry_gets_the_answer_but_an_answered_one_is_never_overwritten(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    eid = qbank.add_entry(conn, question="Notice period?", kind="text", answer="", embed=fake_embed)
    promote_answer(conn, _f("Notice period?"), "30 days", fake_embed)
    assert qbank.get_entry(conn, eid)["answer"] == "30 days"
    assert promote_answer(conn, _f("Notice period?"), "60 days", fake_embed) is None
    assert qbank.get_entry(conn, eid)["answer"] == "30 days"


def test_company_specific_essays_files_and_blank_answers_stay_with_the_application(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    before = len(qbank.entries(conn))
    assert promote_answer(conn, _f("Why do you want to join Acme?", "textarea"), "Because agents", fake_embed) is None
    assert promote_answer(conn, _f("Tell us why you are interested in this role"), "x", fake_embed) is None
    assert promote_answer(conn, _f("Upload your CV", "file"), "/tmp/cv.pdf", fake_embed) is None
    assert promote_answer(conn, _f("Expected CTC?"), "   ", fake_embed) is None
    assert len(qbank.entries(conn)) == before


def test_the_run_recorder_promotes_telegram_replies_and_records_the_application_row(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    rec = QARecorder(conn, job_id=5)
    rec.promote_embed = fake_embed
    rec.answered(_f("Are you comfortable with on-call rotations?", ref="#q"), "Yes")
    assert _answers(conn)["Are you comfortable with on-call rotations?"] == "Yes"
    row = conn.execute("SELECT answer, source, status FROM application_qa WHERE ref = '#q'").fetchone()
    assert row == ("Yes", "human", "answered")


def test_without_an_embedder_the_recorder_only_keeps_the_application_row(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    before = len(qbank.entries(conn))
    QARecorder(conn, job_id=5).answered(_f("Are you comfortable with on-call rotations?"), "Yes")
    assert len(qbank.entries(conn)) == before


def test_a_failing_bank_never_breaks_recording(tmp_path, fake_embed):
    conn = _conn(tmp_path, fake_embed)
    rec = QARecorder(conn, job_id=5)
    rec.promote_embed = lambda texts: (_ for _ in ()).throw(RuntimeError("model missing"))
    rec.answered(_f("Are you comfortable with on-call rotations?", ref="#q"), "Yes")
    assert conn.execute("SELECT status FROM application_qa WHERE ref = '#q'").fetchone()[0] == "answered"
