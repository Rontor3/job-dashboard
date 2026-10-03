import json
from types import SimpleNamespace as NS

from career_agent.browser.form_model import Field
from career_agent.integrations.park import ParkCollector, park_human, result_summary, write_result


def _f(ref, label):
    return Field(ref, "text", label, True, [], None, None)


def test_park_collector_answers_nothing_and_notifies_once_per_call():
    sent = []
    c = ParkCollector(notify=sent.append)
    c.context = "Naukri — ML Engineer"
    assert c([_f("a", "Expected CTC"), _f("b", "Notice period")]) == {}
    assert len(sent) == 1
    assert "2 question(s)" in sent[0] and "Naukri — ML Engineer" in sent[0] and "Expected CTC" in sent[0]
    assert c([]) == {} and len(sent) == 1          # nothing to park -> no message


def test_park_collector_never_raises_when_notify_fails():
    def boom(_):
        raise OSError("telegram down")
    assert ParkCollector(notify=boom)([_f("a", "CTC")]) == {}


def test_park_human_never_approves_and_never_waits():
    human = park_human(notify=None)
    assert human.approve("submit?") is False
    assert human.collect([_f("a", "CTC")]) == {}
    assert human.remote_solve(None, "captcha", lambda u: None).sent is False


def test_result_summary_keeps_what_the_queue_needs():
    out = {"url": "u", "board": "board:naukri", "submitted": False, "stopped_reason": "needs_human",
           "decisions": [{"ref": "x"}], "pending_human": [{"ref": "a", "label": "Expected CTC"}, {"ref": "b"}]}
    assert result_summary(out) == {"url": "u", "board": "board:naukri", "submitted": False,
                                   "stopped_reason": "needs_human", "filled": 1,
                                   "pending_human": ["Expected CTC", "b"]}
    assert result_summary(None)["stopped_reason"] == "error"


def test_write_result_writes_json_and_swallows_bad_paths(tmp_path):
    p = tmp_path / "r.json"
    write_result(str(p), {"submitted": True, "stopped_reason": "submitted"})
    assert json.loads(p.read_text())["submitted"] is True
    write_result(str(tmp_path / "missing" / "dir" / "r.json"), {})    # must not raise
    write_result(None, {})                                             # no path -> no-op


def test_board_ask_with_park_human_leaves_the_gap_open():
    from career_agent.boards import run as br
    got, left = br._ask([_f("a", "Expected CTC")], {"human": park_human(notify=None)})
    assert got == [] and [f.ref for f in left] == ["a"]


def test_graph_loop_asks_a_parked_human_once(monkeypatch):
    import sys
    import types
    from career_agent import apply as ap

    pending = [{"ref": "a", "kind": "text", "label": "CTC", "required": True, "options": [],
                "group": None, "purpose": None}]

    class App:
        invokes = 0

        def invoke(self, *_):
            App.invokes += 1
            return {"pending_human": pending}

        def get_state(self, cfg):
            return NS(next=("human_gate",), values={"pending_human": pending})

    graph_mod = types.SimpleNamespace(build_graph=lambda checkpointer=None: App(),
                                      initial_state=lambda *a, **k: {})
    monkeypatch.setitem(sys.modules, "career_agent.orchestrator.graph", graph_mod)
    sent = []
    out = ap._run_graph({"configurable": {}}, "u", None, False, False, 5, park_human(sent.append))
    assert out["pending_human"] == pending
    assert App.invokes == 1 and len(sent) == 1


def test_escalation_context_reads_job_and_company_page_from_the_db(tmp_path):
    from career_agent.apply import _escalation_context
    from job_dashboard.artifacts_store import upsert_company_resources
    from job_dashboard.db import init_db, insert_job
    from job_dashboard.models import JobListing
    conn = init_db(str(tmp_path / "t.db"))
    insert_job(conn, JobListing(source="s", title="ML Eng", company="Acme AI", job_url="http://x/1",
                                description="Ship models."))
    jid = conn.execute("SELECT id FROM jobs").fetchone()[0]
    upsert_company_resources(conn, "acme ai", [{"source_url": "https://acme.ai/about", "title": "About",
                                                "summary": "Agent tooling."}])
    jd, company = _escalation_context(conn, jid, None)
    assert "ML Eng at Acme AI" in jd and "Ship models." in jd
    assert "https://acme.ai/about" in company and "Agent tooling." in company
    jd2, company2 = _escalation_context(conn, None, "scraped page text")
    assert "scraped page text" in jd2 and company2 == ""
