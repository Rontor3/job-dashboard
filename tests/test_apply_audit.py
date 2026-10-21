"""The queue's audit trail for runs the child never recorded, and the cleanup
of open questions on jobs that settled while they waited (run_log backfill +
resolve_settled_questions)."""
import json
import sqlite3

from job_dashboard import autonomy, qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply.queue_runner import QueueRunner
from job_dashboard.apply.submit_watch import SubmitWatcher
from job_dashboard.db import init_db

ROW = ("SELECT ts, url, job_id, stopped_reason, filled, escalated, submitted, result_json "
       "FROM run_log WHERE job_id=? ORDER BY id")


class _Scripted:
    """launch(job_id, argv, result_path) -> exit code; writes the scripted result (or nothing)."""

    def __init__(self, code, result=None):
        self.code, self.result = code, result

    def __call__(self, job_id, argv, result_path):
        if self.result is not None:
            with open(result_path, "w") as fh:
                json.dump(self.result, fh)
        return self.code


def _db(tmp_path, statuses=(None,)):
    path = str(tmp_path / "jobs.db")
    conn = init_db(path)
    for n, status in enumerate(statuses, 1):
        conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at, status) "
                     "VALUES (?, 't', 'c', ?, 's', '', 'now', ?)", (n, f"https://x/job{n}", status))
        q.enqueue(conn, n)
    conn.commit()
    return path, conn


def test_a_stalled_run_that_wrote_no_run_log_row_is_backfilled(tmp_path):
    path, conn = _db(tmp_path)
    QueueRunner(path, _Scripted(code=124), result_dir=str(tmp_path)).drain()   # stall-kill: no result file, no child row
    assert conn.execute("SELECT state, reason FROM apply_queue WHERE job_id=1").fetchone() \
        == ("parked", "stalled_no_progress")
    ts, url, job_id, why, filled, esc, sub, rj = conn.execute(ROW, (1,)).fetchone()
    assert (url, job_id, why, filled, esc, sub) == ("https://x/job1", 1, "stalled_no_progress", 0, 0, 0)
    assert "T" in ts and "+" not in ts and not ts.endswith("Z")               # naive UTC isoformat, as the child writes them
    payload = json.loads(rj)
    assert payload["backfill"] is True and payload["exit_code"] == 124 and payload["result"] is None
    assert "backfilled by the queue runner" in payload["note"]


def test_a_no_entry_run_with_no_row_is_backfilled_then_discovered(tmp_path):
    path, conn = _db(tmp_path)
    QueueRunner(path, _Scripted(0, {"submitted": False, "stopped_reason": "no_entry"}),
                result_dir=str(tmp_path)).drain()
    _, _, _, why, _, _, _, rj = conn.execute(ROW, (1,)).fetchone()
    assert why == "no_entry"
    payload = json.loads(rj)
    assert payload["backfill"] is True and payload["exit_code"] == 0
    assert payload["result"] == {"submitted": False, "stopped_reason": "no_entry"}
    # and the point of it: the watcher now discovers this blocked run from run_log
    autonomy.ensure(conn)
    SubmitWatcher(path).register_fresh_blocks(conn)
    run_key, tab_id, how = conn.execute("SELECT run_key, tab_id, how FROM submission_watch WHERE job_id=1").fetchone()
    assert how == "no_entry" and tab_id is None and run_key.startswith("run")   # no run_key/final_tab_id to inherit


def test_a_claimed_submit_the_child_never_logged_is_backfilled_too(tmp_path):
    path, conn = _db(tmp_path)
    QueueRunner(path, _Scripted(0, {"submitted": True, "stopped_reason": "submitted"}),
                result_dir=str(tmp_path)).drain()
    ts, _, _, why, _, _, sub, rj = conn.execute(ROW, (1,)).fetchone()
    assert (why, sub) == ("submitted", 0)                                   # done/applied is shown no mercy (counters stay 0)
    payload = json.loads(rj)
    assert payload["backfill"] is True and payload["result"]["submitted"] is True
    assert conn.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "applied"


def test_a_child_that_recorded_its_own_row_is_not_backfilled(tmp_path):
    path, conn = _db(tmp_path)

    def launch(job_id, argv, result_path):          # the child logged its row, then died anyway
        child = sqlite3.connect(path)
        try:
            child.execute("INSERT INTO run_log (ts, url, job_id, stopped_reason, result_json) "
                          "VALUES ('2026-10-21T09:00:00','https://x/job1',1,'challenge','{\"escalated_labels\": []}')")
            child.commit()
        finally:
            child.close()
        return 124

    QueueRunner(path, launch, result_dir=str(tmp_path)).drain()
    rows = conn.execute(ROW, (1,)).fetchall()
    assert len(rows) == 1                                                   # the child's row, no duplicate
    assert rows[0][1:4] == ("https://x/job1", 1, "challenge")
    assert json.loads(rows[0][7]).get("backfill") is None


def test_settled_jobs_open_questions_are_retired_a_failed_job_keeps_its(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r1", ref="#a", label="Notice period", source="human", status="needs_answer")
    qa_store.record(conn, job_id=8, run_key="r2", ref="#a", label="Notice period", source="human", status="needs_answer")
    conn.commit()
    assert qa_store.open_counts(conn) == {7: 1, 8: 1}
    conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at, status) "
                 "VALUES (7,'t','c','u','s','','now','applied'), (8,'t','c','u8','s','','now','failed')")
    conn.execute("UPDATE application_qa SET updated_at='2000-01-01T00:00:00' WHERE job_id=7")
    conn.commit()
    assert qa_store.resolve_settled_questions(conn) == 1
    status, basis, answer, source, updated = conn.execute("SELECT status, basis, answer, source, updated_at "
                                                          "FROM application_qa WHERE job_id=7").fetchone()
    assert status == "obsolete" and "job is applied" in basis and "resolved obsolete" in basis
    assert answer is None and source == "human"                             # nothing became an answer
    assert updated != "2000-01-01T00:00:00"                                 # freshly touched
    assert qa_store.prior_answers(conn, 7) == {}                            # never picked up as a human answer
    assert qa_store.open_questions(conn, 7) == [] and qa_store.open_counts(conn) == {8: 1}
    assert conn.execute("SELECT status FROM application_qa WHERE job_id=8").fetchone()[0] == "needs_answer"
    assert qa_store.resolve_settled_questions(conn) == 0                    # idempotent


def test_the_watchers_reconcile_pass_resolves_settled_questions(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r1", ref="#a", label="Notice period", status="needs_answer")
    conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at, status) "
                 "VALUES (7,'t','c','u','s','','now','applied')")
    conn.commit()
    w = SubmitWatcher(str(tmp_path / "t.db"))
    assert w._last_reconcile == 0.0                                          # never ran: immediately due
    w._reconcile_if_due(conn)                                                # gmail off by default, yet it resolves
    assert conn.execute("SELECT status FROM application_qa WHERE job_id=7").fetchone()[0] == "obsolete"
    assert w._last_reconcile > 0
    w._last_reconcile = 0.0
    w._reconcile_if_due(conn)                                               # a second pass retires nothing further
    assert qa_store.open_counts(conn) == {}
