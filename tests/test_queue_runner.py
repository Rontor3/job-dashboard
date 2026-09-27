import json

from job_dashboard import qa_store
from job_dashboard.apply import queue as q
from job_dashboard.apply.queue_runner import QueueRunner, autosubmit_key, job_target
from job_dashboard.db import init_db

URLS = {1: "https://www.naukri.com/job-listings-ml-1", 2: "https://boards.greenhouse.io/acme/jobs/2",
        3: "https://www.iimjobs.com/j/data-3"}


def _db(tmp_path, ids=(1, 2, 3)):
    path = str(tmp_path / "jobs.db")
    conn = init_db(path)
    for i in ids:
        conn.execute("INSERT INTO jobs (id, title, company, job_url, source, description, fetched_at)"
                     " VALUES (?, 't', 'c', ?, 's', '', 'now')", (i, URLS[i]))
        q.enqueue(conn, i)
    conn.commit()
    return path, conn


class FakeLaunch:
    """launch(job_id, argv, result_path) -> exit code; writes the scripted result."""

    def __init__(self, results):
        self.results, self.calls = results, []

    def __call__(self, job_id, argv, result_path):
        self.calls.append((job_id, argv))
        code, res = self.results.get(job_id, (0, {"submitted": True, "stopped_reason": "submitted"}))
        if isinstance(res, Exception):
            raise res
        if res is not None:
            with open(result_path, "w") as fh:
                json.dump(res, fh)
        return code


def _states(conn):
    return {r["job_id"]: (r["state"], r["reason"]) for r in q.list_queue(conn)}


def test_runs_every_queued_job_in_order_and_maps_outcomes(tmp_path):
    path, conn = _db(tmp_path)
    launch = FakeLaunch({2: (0, {"submitted": False, "stopped_reason": "needs_human", "pending_human": ["CTC"]}),
                         3: (1, None)})
    QueueRunner(path, launch, result_dir=str(tmp_path)).drain()
    assert [c[0] for c in launch.calls] == [1, 2, 3]
    assert _states(conn) == {1: ("done", "submitted"), 2: ("parked", "needs_answers"), 3: ("failed", "crashed")}
    status = dict(conn.execute("SELECT id, status FROM jobs").fetchall())
    assert status[1] == "applied" and status[2] is None


def test_argv_parks_and_submits_only_where_authorized(tmp_path):
    path, conn = _db(tmp_path)
    qa_store.set_setting(conn, autosubmit_key(URLS[1]), "1")      # naukri on, others off
    launch = FakeLaunch({})
    QueueRunner(path, launch, result_dir=str(tmp_path)).drain()
    argv = {j: a for j, a in launch.calls}
    for a in argv.values():
        assert "--park" in a and "--result-json" in a and "--job-id" in a
    assert "--submit" in argv[1] and "--autonomous" in argv[1] and "--review" not in argv[1]
    assert "--submit" not in argv[2] and "--review" in argv[2]
    assert argv[1][argv[1].index("--url") + 1] == URLS[1]


def test_autosubmit_key_per_board_and_career_site():
    assert autosubmit_key(URLS[1]) == "autosubmit_naukri"
    assert autosubmit_key(URLS[3]) == "autosubmit_iimjobs"
    assert autosubmit_key(URLS[2]) == "autosubmit_career_site"


def test_job_target_prefers_external_apply_url():
    assert job_target({"job_url": "j", "apply_kind": "external", "apply_url": "a"}) == "a"
    assert job_target({"job_url": "j", "apply_kind": "native", "apply_url": "a"}) == "j"


def test_launcher_exception_fails_that_job_and_the_queue_continues(tmp_path):
    path, conn = _db(tmp_path, ids=(1, 2))
    launch = FakeLaunch({1: (0, RuntimeError("chrome gone"))})
    QueueRunner(path, launch, result_dir=str(tmp_path)).drain()
    assert _states(conn) == {1: ("failed", "launch_error"), 2: ("done", "submitted")}


def test_pause_finishes_the_current_job_and_takes_no_next(tmp_path):
    path, conn = _db(tmp_path)
    runner = QueueRunner(path, None, result_dir=str(tmp_path))

    def launch(job_id, argv, result_path):
        runner.pause()                                     # pressed while job 1 runs
        return FakeLaunch({})(job_id, argv, result_path)

    runner.launch = launch
    runner.drain()
    assert _states(conn) == {1: ("done", "submitted"), 2: ("queued", None), 3: ("queued", None)}
    assert runner.status()["paused"] is True


def test_start_runs_in_a_thread_and_is_single_flight(tmp_path):
    path, conn = _db(tmp_path, ids=(1,))
    runner = QueueRunner(path, FakeLaunch({}), result_dir=str(tmp_path))
    assert runner.start() is True
    runner._thread.join(timeout=5)
    assert _states(conn) == {1: ("done", "submitted")}
    assert runner.status() == {"running": False, "paused": False, "job_id": None}


def test_missing_job_row_fails_without_launching(tmp_path):
    path, conn = _db(tmp_path, ids=(1,))
    q.enqueue(conn, 99)
    launch = FakeLaunch({})
    QueueRunner(path, launch, result_dir=str(tmp_path)).drain()
    assert _states(conn)[99] == ("failed", "job_missing") and [c[0] for c in launch.calls] == [1]
