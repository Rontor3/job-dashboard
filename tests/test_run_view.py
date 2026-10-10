import json

from fastapi.testclient import TestClient

from career_agent.boards.run_log import BoardRunLog
from career_agent.browser.form_model import Field
from career_agent.orchestrator.answering import answer_fields
from career_agent.orchestrator.mapper import FillDecision
from career_agent.orchestrator.qa_recorder import QARecorder
from job_dashboard import qa_store
from job_dashboard.api import agent_routes
from job_dashboard.api.app import create_app
from job_dashboard.db import init_db, insert_job
from job_dashboard.models import JobListing


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn)
    return conn


def _rec(conn, run, ref, label, page, **kw):
    qa_store.record(conn, job_id=1, run_key=run, ref=ref, label=label, page=page, **kw)


def test_origin_says_where_each_answer_came_from():
    o = qa_store.origin
    assert o({"status": "filled", "source": "qbank", "retrieval_kind": "exact"}) == "saved_exact"
    assert o({"status": "filled", "source": "qbank", "retrieval_kind": "shortlist"}) == "saved"
    assert o({"status": "needs_answer", "source": "qbank_likely"}) == "similar"
    assert o({"status": "filled", "source": "qbank_likely"}) == "similar"
    assert o({"status": "filled", "source": "judgment"}) == "model"
    assert o({"status": "answered", "source": "human"}) == "you"
    assert o({"status": "filled", "source": "board_prefill"}) == "board"
    assert o({"status": "filled", "source": "standard"}) == "profile"
    assert o({"status": "filled", "source": "resume"}) == "profile"
    assert o({"status": "needs_answer", "source": None}) == "open"
    assert o({"status": "needs_answer", "source": "judgment"}) == "open"      # a draft below the confidence bar


def test_questions_by_page_uses_the_latest_run_only_and_keeps_page_order(tmp_path):
    conn = _conn(tmp_path)
    _rec(conn, "old", "#x", "Old question", 0, status="filled", source="qbank")
    _rec(conn, "new", "#a", "Notice period?", 0, answer="30 days", status="filled", source="qbank",
         retrieval_kind="exact", retrieved_qkey="notice period?")
    _rec(conn, "new", "#b", "Why Acme?", 1, answer="Because agents", status="filled", source="judgment",
         confidence=72, basis="from JD", context_json={"prompt": "PROMPT"})
    _rec(conn, "new", "#c", "Expected CTC?", 1, status="needs_answer")
    by_page = qa_store.questions_by_page(conn, 1)
    assert sorted(by_page) == [0, 1]
    assert [q["label"] for q in by_page[1]] == ["Why Acme?", "Expected CTC?"]
    first = by_page[0][0]
    assert (first["origin"], first["matched"], first["answer"]) == ("saved_exact", "notice period?", "30 days")
    model = by_page[1][0]
    assert (model["origin"], model["confidence"], model["basis"]) == ("model", 72, "from JD")
    assert model["prompt"] == "PROMPT"
    assert by_page[1][1]["origin"] == "open"
    assert "Old question" not in [q["label"] for qs in by_page.values() for q in qs]


def test_rows_without_a_page_land_under_none(tmp_path):
    conn = _conn(tmp_path)
    qa_store.record(conn, job_id=1, run_key="r", ref="#a", label="Q", status="filled", source="human")
    assert list(qa_store.questions_by_page(conn, 1)) == [None]
    assert qa_store.questions_by_page(conn, 99) == {}


def test_the_recorder_tags_rows_with_the_current_page(tmp_path):
    conn = _conn(tmp_path)
    rec = QARecorder(conn, 1)
    rec.page = 3
    rec.decision(FillDecision("#a", "text", "Notice period?", "30 days", "fill", "qbank"))
    assert conn.execute("SELECT page FROM application_qa WHERE ref='#a'").fetchone()[0] == 3


def test_answer_fields_sets_the_page_before_recording_both_pipelines_use_it(tmp_path, monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))
    conn = _conn(tmp_path)
    rec = QARecorder(conn, 1)
    answer_fields([Field("#a", "text", "Anything else?", True, [], None, None)],
                  {"profile": None, "qa": rec, "page_index": 2})
    assert conn.execute("SELECT page FROM application_qa WHERE ref='#a'").fetchone()[0] == 2


def test_board_run_log_hands_out_page_numbers_even_when_logging_is_off(tmp_path):
    class Page:
        url = "u"

        def evaluate(self, *_):
            pass

        def wait_for_timeout(self, *_):
            pass

        def screenshot(self, path, full_page=False, **_):
            open(path, "wb").write(b"x")

    off, on = BoardRunLog(None), BoardRunLog(str(tmp_path))
    assert [off.page(Page()), off.page(Page())] == [0, 1]
    assert [on.page(Page()), on.page(Page())] == [0, 1]
    assert [s["step"] for s in on.steps] == [0, 1]


def test_history_endpoint_attaches_each_pages_questions(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    insert_job(conn, JobListing(source="naukri", title="ML", company="Acme",
                                job_url="https://www.naukri.com/job-listings-1", description="jd"))
    _rec(conn, "r", "#a", "Notice period?", 0, answer="30 days", status="filled", source="qbank", retrieval_kind="exact")
    _rec(conn, "r", "#b", "Expected CTC?", 1, status="needs_answer")
    qa_store.record(conn, job_id=1, run_key="r", ref="#z", label="Legacy row", status="filled", source="human")
    conn.close()
    monkeypatch.setattr(agent_routes.paths, "AGENT_RUNS", tmp_path / "data" / "agent_runs")
    run_dir = tmp_path / "data" / "agent_runs" / "1"
    run_dir.mkdir(parents=True)
    (run_dir / "board_run.json").write_text(json.dumps([
        {"step": 0, "kind": "form", "url": "u", "stopped_reason": None, "pending_human": [], "screenshot": None},
        {"step": 1, "kind": "stop", "url": "u", "stopped_reason": "needs_human", "pending_human": [], "screenshot": None}]))
    body = TestClient(create_app(db_path=db)).get("/api/jobs/1/agent-runs/latest").json()
    assert [q["label"] for q in body["steps"][0]["questions"]] == ["Notice period?"]
    assert [q["label"] for q in body["steps"][1]["questions"]] == ["Expected CTC?"]
    assert [q["label"] for q in body["unpaged"]] == ["Legacy row"]
