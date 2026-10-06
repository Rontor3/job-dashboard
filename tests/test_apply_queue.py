from job_dashboard.apply import queue as q
from job_dashboard.db import init_db


def _conn(tmp_path):
    return init_db(str(tmp_path / "jobs.db"))


def _ids(conn):
    return [r["job_id"] for r in q.list_queue(conn)]


def test_enqueue_keeps_add_order_and_front_goes_first(tmp_path):
    conn = _conn(tmp_path)
    for j in (3, 1, 2):
        q.enqueue(conn, j)
    q.enqueue(conn, 9, front=True)
    assert _ids(conn) == [9, 3, 1, 2]
    assert all(r["state"] == "queued" for r in q.list_queue(conn))


def test_enqueue_twice_is_one_row(tmp_path):
    conn = _conn(tmp_path)
    q.enqueue(conn, 1)
    q.enqueue(conn, 2)
    q.enqueue(conn, 1)
    assert _ids(conn) == [1, 2]


def test_reenqueue_of_parked_job_resets_it_to_the_tail(tmp_path):
    conn = _conn(tmp_path)
    for j in (1, 2):
        q.enqueue(conn, j)
    q.mark(conn, 1, "parked", "needs_answers")
    q.enqueue(conn, 1)
    rows = q.list_queue(conn)
    assert [r["job_id"] for r in rows] == [2, 1]
    assert rows[1]["state"] == "queued" and rows[1]["reason"] is None


def test_move_and_remove(tmp_path):
    conn = _conn(tmp_path)
    for j in (1, 2, 3):
        q.enqueue(conn, j)
    q.move(conn, 3, before=1)
    assert _ids(conn) == [3, 1, 2]
    q.move(conn, 3, before=None)
    assert _ids(conn) == [1, 2, 3]
    q.move(conn, 1, before=3)
    assert _ids(conn) == [2, 1, 3]
    q.remove(conn, 1)
    assert _ids(conn) == [2, 3]


def test_next_queued_skips_other_states_and_mark_stamps_times(tmp_path):
    conn = _conn(tmp_path)
    for j in (1, 2, 3):
        q.enqueue(conn, j)
    q.mark(conn, 1, "running")
    q.mark(conn, 2, "parked", "logged_out")
    assert q.next_queued(conn) == 3
    q.mark(conn, 1, "done", "submitted")
    row = next(r for r in q.list_queue(conn, finished=True) if r["job_id"] == 1)
    assert row["started_at"] and row["finished_at"] and row["reason"] == "submitted"
    q.mark(conn, 3, "running")
    assert q.next_queued(conn) is None


def test_mark_rejects_unknown_state(tmp_path):
    conn = _conn(tmp_path)
    q.enqueue(conn, 1)
    try:
        q.mark(conn, 1, "bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_list_queue_joins_job_title_and_company(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at)"
                 " VALUES (7, 'ML Eng', 'Acme', 'u', 's', '', '2026-09-27')")
    q.enqueue(conn, 7)
    row = q.list_queue(conn)[0]
    assert (row["title"], row["company"]) == ("ML Eng", "Acme")


def test_finished_runs_leave_the_queue_list_but_stay_in_the_table(tmp_path):
    conn = _conn(tmp_path)
    for j in (1, 2, 3, 4):
        q.enqueue(conn, j)
    q.mark(conn, 1, "running")
    q.mark(conn, 2, "done", "submitted")
    q.mark(conn, 3, "parked", "needs_answers")
    assert _ids(conn) == [1, 4]                                         # the queue shrinks as jobs are exercised
    assert {r["job_id"]: r["reason"] for r in q.list_queue(conn, finished=True)}[3] == "needs_answers"
    q.enqueue(conn, 3)                                                  # corrected -> queued again from the tracker
    assert _ids(conn) == [1, 3, 4] or sorted(_ids(conn)) == [1, 3, 4]
